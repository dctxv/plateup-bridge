using System;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Pipes;
using System.Threading;
using Controllers;
using UnityEngine;

namespace PlateUpBridge
{
    /// <summary>
    /// One action frame from Python. Held until superseded.
    /// </summary>
    public class BridgeAction
    {
        public long Tick;
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
            try { return (GameStateRequest)Enum.Parse(typeof(GameStateRequest), Request, true); }
            catch { return GameStateRequest.None; }
        }
    }

    /// <summary>
    /// Named pipe server + shared state. Everything here is touched from both the
    /// Unity main thread and the pipe threads, so it is all lock-free or volatile.
    /// </summary>
    public static class Bridge
    {
        public const string PipeName = "plateup_bridge";
        public const int ProtocolVersion = 1;
        public const int MaxOutboundBacklog = 64;

        // Wire traffic.
        public static readonly ConcurrentQueue<string> Inbound = new ConcurrentQueue<string>();
        public static readonly ConcurrentQueue<string> Outbound = new ConcurrentQueue<string>();

        // Shared control state.
        public static volatile bool Connected;
        public static volatile bool Override;          // master switch, F9
        public static long Tick;                        // incremented by the input system
        public static long LastActionTick;              // tick we last received an action on

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
            if (Outbound.Count > MaxOutboundBacklog) return;   // client is not draining; drop
            Outbound.Enqueue(json);
        }

        static void AcceptLoop()
        {
            while (_running)
            {
                try
                {
                    using (var pipe = new NamedPipeServerStream(
                        PipeName, PipeDirection.InOut, 1,
                        PipeTransmissionMode.Byte, PipeOptions.None, 1 << 16, 1 << 16))
                    {
                        pipe.WaitForConnection();
                        if (!_running) return;

                        Drain(Inbound);
                        Drain(Outbound);
                        Connected = true;
                        _warned = false;
                        Debug.Log("[BRIDGE] client connected");

                        var reader = new StreamReader(pipe);
                        var writer = new StreamWriter(pipe) { AutoFlush = true };

                        var readThread = new Thread(() => ReadLoop(reader, pipe))
                        { IsBackground = true, Name = "PlateUpBridgeRead" };
                        readThread.Start();

                        // This thread owns writing.
                        while (_running && pipe.IsConnected)
                        {
                            string msg;
                            if (Outbound.TryDequeue(out msg)) writer.WriteLine(msg);
                            else Thread.Sleep(1);
                        }

                        readThread.Join(500);
                    }
                }
                catch (Exception ex)
                {
                    if (!_warned) { Debug.Log("[BRIDGE] pipe error: " + ex.Message); _warned = true; }
                }
                finally
                {
                    if (Connected) Debug.Log("[BRIDGE] client disconnected");
                    Connected = false;
                }

                Thread.Sleep(200);
            }
        }

        static void ReadLoop(StreamReader reader, NamedPipeServerStream pipe)
        {
            try
            {
                while (_running && pipe.IsConnected)
                {
                    var line = reader.ReadLine();
                    if (line == null) break;
                    if (line.Length == 0) continue;
                    Inbound.Enqueue(line);
                }
            }
            catch (Exception ex)
            {
                Debug.Log("[BRIDGE] read loop ended: " + ex.Message);
            }
        }

        static void Drain(ConcurrentQueue<string> q)
        {
            string _;
            while (q.TryDequeue(out _)) { }
        }
    }
}
