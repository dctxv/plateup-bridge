using System;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Controllers;
using Microsoft.Win32.SafeHandles;
using UnityEngine;

namespace PlateUpBridge
{
    /// <summary>
    /// One action frame from Python. Held until superseded.
    /// </summary>
    public class BridgeAction
    {
        public long Tick = -1;
        public float MoveX;
        public float MoveY;
        public bool Grab;
        public bool Interact;
        public bool Secondary1;
        public bool Secondary2;
        public bool StopMoving;
        public string Request = "None";

        public GameStateRequest ParsedRequest()
        {
            if (string.IsNullOrEmpty(Request)) return GameStateRequest.None;
            switch (Request.Trim().ToLowerInvariant())
            {
                case "none": return GameStateRequest.None;
                case "inlocalmenu": return GameStateRequest.InLocalMenu;
                case "startpractice": return GameStateRequest.StartPractice;
                case "instantjoin": return GameStateRequest.InstantJoin;
                default: return GameStateRequest.None;
            }
        }
    }

    /// <summary>
    /// Named pipe server + shared state. Connected crosses between the pipe and Unity
    /// threads and must remain volatile. Tick, action metadata, queue depth, Override,
    /// and Injected are main-thread-only; never read or write them from a pipe thread.
    /// </summary>
    public static class Bridge
    {
        public const string PipeName = "plateup_bridge";
        public const int ProtocolVersion = 1;
        public const int MaxOutboundBacklog = 64;

        const uint PipeAccessDuplex = 0x00000003;
        const uint FileFlagOverlapped = 0x40000000;
        const int ErrorIoPending = 997;
        const int ErrorPipeConnected = 535;
        const int ErrorBrokenPipe = 109;
        const int ErrorNoData = 232;

        [StructLayout(LayoutKind.Sequential)]
        struct OverlappedData
        {
            public IntPtr Internal;
            public IntPtr InternalHigh;
            public uint Offset;
            public uint OffsetHigh;
            public IntPtr EventHandle;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateNamedPipe(
            string name,
            uint openMode,
            uint pipeMode,
            uint maxInstances,
            uint outBufferSize,
            uint inBufferSize,
            uint defaultTimeout,
            IntPtr securityAttributes);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ConnectNamedPipe(
            SafePipeHandle pipe,
            ref OverlappedData overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetOverlappedResult(
            SafePipeHandle pipe,
            ref OverlappedData overlapped,
            out uint transferred,
            bool wait);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool PeekNamedPipe(
            SafePipeHandle pipe,
            IntPtr buffer,
            uint bufferSize,
            out uint bytesRead,
            out uint bytesAvailable,
            out uint bytesLeftThisMessage);

        // Wire traffic.
        public static readonly ConcurrentQueue<string> Inbound = new ConcurrentQueue<string>();
        public static readonly ConcurrentQueue<string> Outbound = new ConcurrentQueue<string>();

        // Shared control state.
        public static volatile bool Connected;
        public static volatile bool Override;          // master switch, F9
        public static long Tick;                        // incremented by the input system
        public static long LastActionTick;              // tick we last received an action on
        public static long AppliedActionTick = -1;       // action tick enqueued this sim frame
        public static int InputQueueDepth;               // depth before ApplyUpdates drains once
        public static long DroppedOutboundFrames;

        /// <summary>
        /// The InputState the Harmony patch feeds back to the game's own device read.
        /// Written by BridgeInputSystem each tick, read by GetCurrentInputDataPatch.
        /// </summary>
        public static InputState Injected = InputState.Neutral;

        static Thread _thread;
        static volatile bool _running;
        static bool _warned;

        public static void Start()
        {
            if (_running) return;
            _running = true;
            _thread = new Thread(AcceptLoop) { IsBackground = true, Name = "PlateUpBridgePipe" };
            _thread.Start();
            Debug.Log("[BRIDGE] pipe server starting on \\\\.\\pipe\\" + PipeName);
        }

        public static void Stop()
        {
            _running = false;
            Connected = false;
        }

        public static void Send(string json)
        {
            if (!Connected) return;
            if (Outbound.Count > MaxOutboundBacklog)
            {
                Interlocked.Increment(ref DroppedOutboundFrames);
                return;
            }
            Outbound.Enqueue(json);
        }

        static void AcceptLoop()
        {
            while (_running)
            {
                try
                {
                    using (var pipe = CreateConnectedPipe())
                    {
                        if (!_running) return;

                        Drain(Inbound);
                        Drain(Outbound);
                        Connected = true;
                        _warned = false;
                        Debug.Log("[BRIDGE] client connected");

                        PumpConnection(pipe);
                    }
                }
                catch (Exception ex)
                {
                    if (!_warned) { Debug.Log("[BRIDGE] pipe error: " + ex); _warned = true; }
                }
                finally
                {
                    if (Connected) Debug.Log("[BRIDGE] client disconnected");
                    Connected = false;
                }

                Thread.Sleep(200);
            }
        }

        static void PumpConnection(NamedPipeServerStream pipe)
        {
            var readBuffer = new byte[4096];
            string pending = "";

            while (_running && pipe.IsConnected)
            {
                bool worked = false;

                string message;
                while (Outbound.TryDequeue(out message))
                {
                    var bytes = Encoding.UTF8.GetBytes(message + "\n");
                    pipe.Write(bytes, 0, bytes.Length);
                    pipe.Flush();
                    worked = true;
                }

                uint ignored;
                uint available;
                uint left;
                if (!PeekNamedPipe(
                    pipe.SafePipeHandle,
                    IntPtr.Zero,
                    0,
                    out ignored,
                    out available,
                    out left))
                {
                    int error = Marshal.GetLastWin32Error();
                    if (error == ErrorBrokenPipe || error == ErrorNoData) break;
                    throw new IOException("PeekNamedPipe failed: " + error);
                }

                if (available > 0)
                {
                    int count = (int)Math.Min((uint)readBuffer.Length, available);
                    int read = pipe.Read(readBuffer, 0, count);
                    if (read <= 0) break;

                    pending += Encoding.UTF8.GetString(readBuffer, 0, read);
                    int newline;
                    while ((newline = pending.IndexOf('\n')) >= 0)
                    {
                        string line = pending.Substring(0, newline).TrimEnd('\r');
                        pending = pending.Substring(newline + 1);
                        if (line.Length > 0) Inbound.Enqueue(line);
                    }
                    worked = true;
                }

                if (!worked) Thread.Sleep(1);
            }
        }

        static NamedPipeServerStream CreateConnectedPipe()
        {
            var rawHandle = CreateNamedPipe(
                @"\\.\pipe\" + PipeName,
                PipeAccessDuplex | FileFlagOverlapped,
                0,
                1,
                1 << 16,
                1 << 16,
                0,
                IntPtr.Zero);

            if (rawHandle == new IntPtr(-1))
                throw new IOException("CreateNamedPipe failed: " + Marshal.GetLastWin32Error());

            var handle = new SafePipeHandle(rawHandle, true);

            try
            {
                using (var connected = new EventWaitHandle(false, EventResetMode.ManualReset))
                {
                    var overlapped = new OverlappedData
                    {
                        EventHandle = connected.SafeWaitHandle.DangerousGetHandle()
                    };

                    if (!ConnectNamedPipe(handle, ref overlapped))
                    {
                        int error = Marshal.GetLastWin32Error();
                        if (error == ErrorIoPending)
                        {
                            connected.WaitOne();
                            uint transferred;
                            if (!GetOverlappedResult(handle, ref overlapped, out transferred, false))
                                throw new IOException("ConnectNamedPipe failed: " + Marshal.GetLastWin32Error());
                        }
                        else if (error != ErrorPipeConnected)
                        {
                            throw new IOException("ConnectNamedPipe failed: " + error);
                        }
                    }
                }

                return new NamedPipeServerStream(
                    PipeDirection.InOut, true, true, handle);
            }
            catch
            {
                handle.Dispose();
                throw;
            }
        }

        static void Drain(ConcurrentQueue<string> q)
        {
            string _;
            while (q.TryDequeue(out _)) { }
        }
    }
}
