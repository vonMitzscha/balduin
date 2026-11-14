// Starter der Windows-App (Entscheidungen 13. und 14.11.2026, docs/plan.md): startet den Server von Balduin mit dem
// Python im Paket und einer unsichtbaren Konsole (CREATE_NO_WINDOW; Programmaufrufe von Server und Läufen erben sie
// und öffnen kein eigenes Fenster) und hält ein Symbol im Infobereich: „Balduin öffnen“, „Balduin beenden“.
// Läufe laufen in eigener Prozessgruppe weiter, wenn der Server endet.
//
// Bauen (auslieferung/bauen.py) mit dem C#-Compiler des .NET Framework 4 (in jedem Windows enthalten, C# 5):
//   csc /target:winexe /win32icon:balduin.ico /r:System.Windows.Forms.dll /r:System.Drawing.dll /out:Balduin.exe Starter.cs
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

static class Starter
{
    const string ADRESSE = "http://127.0.0.1:8765/";
    const string SPERRE = "BalduinStarter";          // gleicher Name wie AppMutex im Installer (balduin.iss)

    static Process server;
    static NotifyIcon symbol;
    static StreamWriter log;
    static string logPfad;
    static bool beendetSelbst;
    static Control oberflaeche;                       // damit „Exited“ auf dem Faden der Oberfläche ankommt

    [STAThread]
    static void Main()
    {
        bool neu;
        using (var sperre = new Mutex(true, SPERRE, out neu))
        {
            if (!neu)
            {                                         // Balduin läuft schon: nur den Browser öffnen
                Oeffnen();
                return;
            }
            Application.EnableVisualStyles();
            oberflaeche = new Control();
            oberflaeche.CreateControl();
            if (!ServerStarten()) return;
            SymbolZeigen();
            Application.Run();
            GC.KeepAlive(sperre);
        }
    }

    static string Code { get { return Path.GetDirectoryName(Application.ExecutablePath); } }

    static bool ServerStarten()
    {
        var ordner = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Balduin");
        Directory.CreateDirectory(ordner);
        logPfad = Path.Combine(ordner, "server.log");
        log = new StreamWriter(logPfad, false, new System.Text.UTF8Encoding(false));
        log.AutoFlush = true;

        var info = new ProcessStartInfo();
        info.FileName = Path.Combine(Code, "python", "python.exe");
        info.Arguments = "-X utf8 \"" + Path.Combine(Code, "tool", "server.py") + "\"";
        info.WorkingDirectory = Code;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;                   // unsichtbare Konsole statt pythonw.exe (Entscheidung 13.11.2026)
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = System.Text.Encoding.UTF8;
        info.StandardErrorEncoding = System.Text.Encoding.UTF8;
        info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        info.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try
        {
            server = new Process();
            server.StartInfo = info;
            server.EnableRaisingEvents = true;
            server.SynchronizingObject = oberflaeche;
            server.OutputDataReceived += Mitschreiben;
            server.ErrorDataReceived += Mitschreiben;
            server.Exited += ServerBeendet;
            server.Start();
            server.BeginOutputReadLine();
            server.BeginErrorReadLine();
            return true;
        }
        catch (Exception e)
        {
            MessageBox.Show("Balduin lässt sich nicht starten.\n\n" + e.Message, "Balduin",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }
    }

    static void Mitschreiben(object sender, DataReceivedEventArgs e)
    {
        if (e.Data == null) return;
        lock (log) { log.WriteLine(e.Data); }
    }

    static void SymbolZeigen()
    {
        var menue = new ContextMenuStrip();
        var oeffnen = new ToolStripMenuItem("Balduin öffnen", null, delegate { Oeffnen(); });
        oeffnen.Font = new Font(oeffnen.Font, FontStyle.Bold);
        menue.Items.Add(oeffnen);
        menue.Items.Add(new ToolStripSeparator());
        menue.Items.Add(new ToolStripMenuItem("Balduin beenden", null, delegate { Beenden(); }));

        symbol = new NotifyIcon();
        symbol.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        symbol.Text = "Balduin";
        symbol.ContextMenuStrip = menue;
        symbol.DoubleClick += delegate { Oeffnen(); };
        symbol.Visible = true;
        symbol.ShowBalloonTip(6000, "Balduin läuft",
            "Balduin öffnet sich im Browser. Öffnen und Beenden über dieses Symbol im Infobereich.", ToolTipIcon.Info);
    }

    static void Oeffnen()
    {
        try { Process.Start(ADRESSE); } catch (Exception) { }
    }

    // Der Server endet von selbst: Balduin lief schon (Browser wurde dorthin geöffnet) oder ein Fehler
    static void ServerBeendet(object sender, EventArgs e)
    {
        if (beendetSelbst) return;
        if (server.ExitCode != 0)
        {
            string text;
            lock (log) { log.Flush(); }
            try
            {
                var zeilen = File.ReadAllLines(logPfad, System.Text.Encoding.UTF8);
                text = string.Join("\n", zeilen.Skip(Math.Max(0, zeilen.Length - 6)).ToArray());
            }
            catch (Exception) { text = ""; }
            MessageBox.Show("Balduin wurde unerwartet beendet.\n\n" + text + "\n\nAlle Meldungen: " + logPfad, "Balduin",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        Aufraeumen();
        Application.Exit();
    }

    static void Beenden()
    {
        beendetSelbst = true;
        try { if (!server.HasExited) server.Kill(); } catch (Exception) { }   // nur der Server; Läufe laufen weiter
        Aufraeumen();
        Application.Exit();
    }

    static void Aufraeumen()
    {
        if (symbol != null) { symbol.Visible = false; symbol.Dispose(); }
    }
}
