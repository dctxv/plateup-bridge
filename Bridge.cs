using System;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
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
        public long CommandId;
        public float MoveX;
        public float MoveY;
        public bool Grab;
        public bool Interact;
        public bool Secondary1;
        public bool Secondary2;
        public bool StopMoving;
        public bool Ready;
        public bool MenuSelect;
        public bool MenuCancel;
        public bool MenuUp;
        public bool MenuDown;
        public bool MenuLeft;
        public bool MenuRight;
        public string Request = "None";

        public GameStateRequest ParsedRequest()
        {
            if (string.IsNullOrEmpty(Request)) return GameStateRequest.None;
            switch (Request.Trim().ToLowerInvariant())
            {
                case "none": return GameStateRequest.None;
                case "inlocalmenu": return GameStateRequest.InLocalMenu;
                case "quitsection": return GameStateRequest.QuitSection;
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
        public const string ObsSchema = "obs_0.1";
        public const string ActSchema = "act_0.1";
        public const string BridgeVersion = "0.2.1";
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

        // Command receipt state. ResetCommandReceipts is raised by the pipe thread
        // and consumed by BridgeInputSystem on Unity's main thread.
        public static long LastCommandId;
        public static long CommandsApplied;
        public static long CommandsDropped;
        public static volatile bool ResetCommandReceipts;

        // Run provenance. SessionId is new for every game launch.
        public static readonly string SessionId = Guid.NewGuid().ToString("N");
        public static string GameVersion = "unknown";
        public static string UnityVersion = "unknown";
        public static string ModHash = "unknown";

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
            GameVersion = Application.version;
            UnityVersion = Application.unityVersion;
            ModHash = ComputeModHash();
            _thread = new Thread(AcceptLoop) { IsBackground = true, Name = "PlateUpBridgePipe" };
            _thread.Start();
            Debug.Log("[BRIDGE] pipe server starting on \\\\.\\pipe\\" + PipeName
                      + " | game=" + GameVersion + " mod=" + ModHash);
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

        static string Hello()
        {
            return "{\"kind\":\"hello\""
                 + ",\"protocol\":" + ProtocolVersion
                 + ",\"bridge_version\":\"" + BridgeVersion + "\""
                 + ",\"obs_schema\":\"" + ObsSchema + "\""
                 + ",\"act_schema\":\"" + ActSchema + "\""
                 + ",\"session_id\":\"" + SessionId + "\""
                 + ",\"game_version\":\"" + GameVersion + "\""
                 + ",\"mod_hash\":\"" + ModHash + "\""
                 + ",\"unity\":\"" + UnityVersion + "\""
                 + "}";
        }

        static string ComputeModHash()
        {
            try
            {
                var path = typeof(Bridge).Assembly.Location;
                if (string.IsNullOrEmpty(path) || !File.Exists(path)) return "unknown";
                using (var sha = SHA256.Create())
                using (var stream = File.OpenRead(path))
                {
                    return BitConverter.ToString(sha.ComputeHash(stream))
                        .Replace("-", "")
                        .Substring(0, 16)
                        .ToLowerInvariant();
                }
            }
            catch
            {
                return "unknown";
            }
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
                        ResetCommandReceipts = true;
                        _warned = false;
                        Debug.Log("[BRIDGE] client connected");

                        WriteFrame(pipe, Hello());
                        Connected = true;
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
                    WriteFrame(pipe, message);
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

        static void WriteFrame(NamedPipeServerStream pipe, string message)
        {
            var bytes = Encoding.UTF8.GetBytes(message + "\n");
            pipe.Write(bytes, 0, bytes.Length);
            pipe.Flush();
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
