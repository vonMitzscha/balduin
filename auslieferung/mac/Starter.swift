// Starter der Mac-App (Entscheidung 14.11.2026, docs/plan.md): startet den Server von Balduin mit dem Python im
// Paket ohne Terminalfenster und hält ein Symbol im Dock. Klick aufs Symbol öffnet Balduin im Browser, „Beenden“
// beendet den Server (Läufe laufen in eigener Sitzung weiter, wie beim Schließen des Terminalfensters).
//
// Bauen (auslieferung/bauen.py):  swiftc -O -target arm64-apple-macos11 Starter.swift -o Balduin
import Cocoa

let ADRESSE = URL(string: "http://127.0.0.1:8765/")!

final class Starter: NSObject, NSApplicationDelegate {
    var server: Process?
    var log: FileHandle?
    var beendetSelbst = false

    // Ordner des Codes im Paket: Balduin.app/Contents/Resources/balduin
    var code: URL { Bundle.main.resourceURL!.appendingPathComponent("balduin") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        menueBauen()
        serverStarten()
    }

    func menueBauen() {
        let leiste = NSMenu()
        let app = NSMenuItem()
        leiste.addItem(app)
        let menue = NSMenu(title: "Balduin")
        menue.addItem(withTitle: "Balduin öffnen", action: #selector(oeffnen), keyEquivalent: "o")
        menue.addItem(NSMenuItem.separator())
        menue.addItem(withTitle: "Balduin beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = menue
        NSApp.mainMenu = leiste
    }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menue = NSMenu()
        menue.addItem(withTitle: "Balduin öffnen", action: #selector(oeffnen), keyEquivalent: "")
        return menue
    }

    // Klick aufs Dock-Symbol, während Balduin läuft
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        oeffnen()
        return false
    }

    @objc func oeffnen() {
        NSWorkspace.shared.open(ADRESSE)
    }

    func logDatei() -> FileHandle? {
        let ordner = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Balduin", isDirectory: true)
        try? FileManager.default.createDirectory(at: ordner, withIntermediateDirectories: true)
        let datei = ordner.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: datei.path, contents: nil)       // bei jedem Start neu
        return try? FileHandle(forWritingTo: datei)
    }

    func serverStarten() {
        let p = Process()
        p.executableURL = code.appendingPathComponent("python/bin/python3")
        p.arguments = ["-X", "utf8", code.appendingPathComponent("tool/server.py").path]
        p.currentDirectoryURL = code
        var umgebung = ProcessInfo.processInfo.environment
        umgebung["PYTHONDONTWRITEBYTECODE"] = "1"          // nichts ins signierte Programm schreiben
        umgebung["PYTHONNOUSERSITE"] = "1"                 // keine Pakete aus dem persönlichen Ordner
        p.environment = umgebung
        log = logDatei()
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { prozess in
            DispatchQueue.main.async { self.serverBeendet(prozess) }
        }
        do {
            try p.run()
            server = p
        } catch {
            fehler("Balduin lässt sich nicht starten.", error.localizedDescription)
            NSApp.terminate(nil)
        }
    }

    // Der Server endet von selbst: ein anderes Balduin belegt die Adresse (der Browser wurde dorthin geöffnet) oder ein
    // Fehler. Ein zweiter Start dieser App kommt hier nicht an (macOS aktiviert dann die laufende), also ist das andere
    // Balduin eines außerhalb der App, z. B. aus einem Terminalfenster.
    func serverBeendet(_ prozess: Process) {
        if beendetSelbst { return }
        if prozess.terminationStatus != 0 {
            fehler("Balduin wurde unerwartet beendet.", letzteZeilen())
        } else if logText().contains("läuft bereits") {
            fehler("Balduin läuft schon in einem anderen Fenster.",
                   "Der Browser zeigt dieses andere Balduin. Um die App zu nutzen, das andere Balduin beenden "
                   + "(zum Beispiel sein Terminalfenster schließen) und die App erneut öffnen.")
        }
        NSApp.terminate(nil)
    }

    func logText() -> String {
        let datei = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Balduin/server.log")
        return (try? String(contentsOf: datei, encoding: .utf8)) ?? ""
    }

    func letzteZeilen() -> String {
        let zeilen = logText().split(separator: "\n").suffix(6).joined(separator: "\n")
        return zeilen + "\n\nAlle Meldungen: ~/Library/Logs/Balduin/server.log"
    }

    func fehler(_ titel: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = titel
        a.informativeText = text
        a.alertStyle = .warning
        a.runModal()
    }

    func applicationWillTerminate(_ notification: Notification) {
        guard let p = server, p.isRunning else { return }
        beendetSelbst = true
        kill(p.processIdentifier, SIGINT)                  // wie Ctrl+C im Terminal: der Server endet sauber
        let frist = Date().addingTimeInterval(5)
        while p.isRunning && Date() < frist { usleep(100_000) }
        if p.isRunning { p.terminate() }
    }
}

let app = NSApplication.shared
let starter = Starter()
app.delegate = starter
app.setActivationPolicy(.regular)
app.run()
