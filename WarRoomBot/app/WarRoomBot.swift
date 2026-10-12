// Native macOS controller. Build in Swift 5 mode for macOS 12 or newer.
// The UI owns Accessibility permission; all bot actions stay in app/wrb.sh.
import Cocoa
import ApplicationServices
import Foundation

struct AppPaths {
    let payload: URL
    let backend: URL
    let helper: URL
    let home: URL
    let version: String
    let name: String

    init() {
        let bundle = Bundle.main
        let resources = bundle.resourceURL ?? bundle.bundleURL.appendingPathComponent("Contents/Resources")
        let payloadURL = resources.appendingPathComponent("payload", isDirectory: true)
        payload = payloadURL
        backend = payloadURL.appendingPathComponent("app/wrb.sh")
        let binaries = bundle.executableURL?.deletingLastPathComponent()
            ?? bundle.bundleURL.appendingPathComponent("Contents/MacOS")
        helper = binaries.appendingPathComponent("axctl")
        let override = ProcessInfo.processInfo.environment["WARROOM_HOME"] ?? ""
        home = override.isEmpty
            ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("WarRoomBot", isDirectory: true)
            : URL(fileURLWithPath: override, isDirectory: true)
        version = (try? String(contentsOf: payloadURL.appendingPathComponent("VERSION"), encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? "unknown"
        name = bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String
            ?? bundle.object(forInfoDictionaryKey: "CFBundleName") as? String ?? "War Room Bot"
    }

    var environment: [String: String] {
        var result = ProcessInfo.processInfo.environment
        result["WARROOM_HOME"] = home.path
        result["WARROOM_AXCTL"] = helper.path
        let preferred = ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin"]
        let inherited = (result["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        result["PATH"] = (preferred + inherited).filter { seen.insert($0).inserted }.joined(separator: ":")
        result["PYTHONUNBUFFERED"] = "1"
        return result
    }

    func smokeTest() -> Int32 {
        var errors: [String] = []
        let manager = FileManager.default
        if !manager.isReadableFile(atPath: backend.path) { errors.append("payload app/wrb.sh is missing or unreadable") }
        if !manager.isExecutableFile(atPath: helper.path) { errors.append("bundled axctl is missing or not executable") }
        if version == "unknown" || version.isEmpty { errors.append("payload VERSION is missing or empty") }
        if (Bundle.main.bundleIdentifier ?? "").isEmpty { errors.append("CFBundleIdentifier is missing") }
        if name != "War Room Bot" { errors.append("app display name must be War Room Bot") }
        let report: [String: Any] = [
            "ok": errors.isEmpty, "name": name, "bundle_id": Bundle.main.bundleIdentifier ?? "",
            "version": version, "home": home.path, "payload": payload.path,
            "helper": helper.path, "errors": errors
        ]
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) { print(text) }
        else { print("Smoke test could not serialize its result.") }
        return errors.isEmpty ? 0 : 1
    }
}

struct BackendResult {
    let code: Int32
    let output: String
}

final class CommandCapture {
    let url: URL
    let handle: FileHandle

    init() throws {
        let location = FileManager.default.temporaryDirectory.appendingPathComponent("war-room-bot-\(UUID().uuidString).log")
        guard FileManager.default.createFile(atPath: location.path, contents: nil,
                                            attributes: [.posixPermissions: NSNumber(value: 0o600)]) else {
            throw NSError(domain: "WarRoomBot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not create command output file."])
        }
        let writer: FileHandle
        do { writer = try FileHandle(forWritingTo: location) }
        catch { try? FileManager.default.removeItem(at: location); throw error }
        url = location
        handle = writer
    }

    func text() -> String { CommandCapture.tail(of: url) }

    static func tail(of url: URL) -> String {
        guard let reader = try? FileHandle(forReadingFrom: url) else { return "Command output could not be read." }
        defer { try? reader.close() }
        do {
            let length = try reader.seekToEnd()
            let limit: UInt64 = 65536
            try reader.seek(toOffset: length > limit ? length - limit : 0)
            let data = try reader.read(upToCount: Int(limit)) ?? Data()
            return (length > limit ? "[Earlier command output omitted]\n" : "")
                + String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        } catch { return "Command output could not be read: \(error.localizedDescription)" }
    }

    func cleanup() { try? handle.close(); try? FileManager.default.removeItem(at: url) }
    deinit { cleanup() }
}

final class Backend {
    let paths: AppPaths
    init(paths: AppPaths) { self.paths = paths }

    func call(_ arguments: [String]) -> BackendResult {
        let task = Process()
        let output: CommandCapture
        do { output = try CommandCapture() }
        catch { return BackendResult(code: 1, output: error.localizedDescription) }
        defer { output.cleanup() }
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = [paths.backend.path] + arguments
        task.environment = paths.environment
        task.currentDirectoryURL = paths.payload
        task.standardInput = FileHandle.nullDevice
        task.standardOutput = output.handle
        task.standardError = output.handle
        let finished = DispatchSemaphore(value: 0)
        task.terminationHandler = { _ in finished.signal() }
        do {
            try task.run()
            let seconds = arguments.first == "stop" ? 180 : arguments.first == "check" ? 120 : 60
            if finished.wait(timeout: .now() + .seconds(seconds)) == .timedOut {
                if task.isRunning { task.terminate() } // Only this ordinary controller, never the live worker.
                _ = finished.wait(timeout: .now() + .seconds(2))
                return BackendResult(code: 1, output: "Controller timed out. Check Status and Diagnostics before retrying.\n\n" + output.text())
            }
            var text = output.text()
            if task.terminationReason == .uncaughtSignal {
                text += "\nController process ended with signal \(task.terminationStatus)."
                return BackendResult(code: 128 + task.terminationStatus, output: text)
            }
            return BackendResult(code: task.terminationStatus, output: text)
        } catch {
            return BackendResult(code: 1, output: "Could not run the bot controller: \(error.localizedDescription)")
        }
    }

    func asynchronously(_ arguments: [String], completion: @escaping (BackendResult) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = self.call(arguments)
            DispatchQueue.main.async { completion(result) }
        }
    }

    func launchWatcher(_ command: String, completion: @escaping (BackendResult) -> Void) throws -> Process {
        let task = Process()
        let output = try CommandCapture()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = [paths.backend.path, command]
        var environment = paths.environment
        environment["WARROOM_APP_FOREGROUND"] = "1"
        task.environment = environment
        task.currentDirectoryURL = paths.payload
        task.standardInput = FileHandle.nullDevice
        task.standardOutput = output.handle
        task.standardError = output.handle
        task.terminationHandler = { finished in
            let text = output.text()
            output.cleanup()
            let code = finished.terminationReason == .uncaughtSignal ? 128 + finished.terminationStatus : finished.terminationStatus
            DispatchQueue.main.async { completion(BackendResult(code: code, output: text)) }
        }
        try task.run()
        return task
    }
}

enum BotAction: String, CaseIterable {
    case check = "Check meeting"
    case dryTest = "Dry run: test number"
    case startTest = "Start: test number"
    case previewRoster = "Preview on-duty roster"
    case dryRoster = "Dry run: roster"
    case startRoster = "Start: roster"
    case stop = "Stop watcher"
    case status = "Status"
    case recent = "Recent activity"
    case changeNumber = "Change test phone number"
    case openData = "Open data folder"
    case setup = "Set up / Update / Repair"
    case requestPermission = "Request Accessibility permission"
    case permission = "Open Accessibility Settings"
    case diagnostics = "Diagnostics"
    case quit = "Quit"
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let paths: AppPaths
    let backend: Backend
    private var window: NSWindow!
    private let stateLabel = NSTextField(labelWithString: "Checking installation…")
    private let watcherLabel = NSTextField(labelWithString: "Watcher: checking…")
    private let permissionLabel = NSTextField(labelWithString: "App Accessibility: checking…")
    private let progressLabel = NSTextField(labelWithString: "")
    private let progressBar = NSProgressIndicator()
    private let picker = NSPopUpButton(frame: .zero, pullsDown: false)
    private let goButton = NSButton(title: "Go", target: nil, action: nil)
    private let stopButton = NSButton(title: "Stop", target: nil, action: nil)
    private let settingsButton = NSButton(title: "Accessibility Settings", target: nil, action: nil)
    private let requestButton = NSButton(title: "Request Accessibility", target: nil, action: nil)
    private let setupButton = NSButton(title: "Set up / Update / Repair", target: nil, action: nil)
    private let outputView = NSTextView()
    private var progressStack: NSStackView!
    private var timer: Timer?
    private var state = "UNKNOWN"
    private var setupActive = false
    private var polling = false
    private var busyCount = 0
    private var pollGeneration = 0
    private var watcherRunning = false
    private var quitApproved = false
    private var quitAfterWorkerStops = false
    private var quitWaitsForOwnedCompletion = false
    private var workerProcess: Process?
    private var workerStarting = false
    private var stopRequested = false
    private var stopInFlight = false
    private var cancellationTimer: Timer?
    private var actionGeneration = 0
    private var workerGeneration = 0
    private var helperPermission = "not checked"
    private var statusItem: NSStatusItem?
    private var reportedPollError = ""

    init(paths: AppPaths) {
        self.paths = paths
        backend = Backend(paths: paths)
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let identifier = Bundle.main.bundleIdentifier,
           let other = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
            .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier
                && $0.executableURL?.lastPathComponent == Bundle.main.executableURL?.lastPathComponent }) {
            other.activate(options: [.activateIgnoringOtherApps])
            quitApproved = true
            NSApp.terminate(nil)
            return
        }
        buildMenu()
        buildWindow()
        showOutput("Version \(paths.version)\nData folder: \(paths.home.path)\n\nUse Check and a dry run before starting live calls. App permission and helper permission are checked separately in Diagnostics.")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.poll() }
    }

    private func buildMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu(title: "War Room Bot")
        let quit = NSMenuItem(title: "Quit War Room Bot", action: #selector(quitAction), keyEquivalent: "q")
        quit.target = self
        appMenu.addItem(quit)
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "WRB"
        let statusMenu = NSMenu()
        let show = NSMenuItem(title: "Open War Room Bot", action: #selector(openWindowAction), keyEquivalent: "")
        show.target = self
        statusMenu.addItem(show)
        let stopQuit = NSMenuItem(title: "Stop and quit", action: #selector(stopAndQuitAction), keyEquivalent: "")
        stopQuit.target = self
        statusMenu.addItem(stopQuit)
        item.menu = statusMenu
        statusItem = item
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 600),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "War Room Bot"
        window.minSize = NSSize(width: 640, height: 440)
        window.center()
        window.delegate = self
        window.isReleasedWhenClosed = false
        let title = NSTextField(labelWithString: "War Room Bot  ·  \(paths.version)")
        title.font = .boldSystemFont(ofSize: 19)
        permissionLabel.font = .systemFont(ofSize: 12)
        permissionLabel.textColor = .secondaryLabelColor
        for label in [stateLabel, watcherLabel, permissionLabel, progressLabel] {
            label.lineBreakMode = .byTruncatingMiddle
            label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        }
        picker.addItems(withTitles: BotAction.allCases.map { $0.rawValue })
        picker.target = self
        picker.action = #selector(selectionChanged)
        goButton.target = self
        goButton.action = #selector(goAction)
        goButton.keyEquivalent = "\r"
        stopButton.target = self
        stopButton.action = #selector(stopAction)
        settingsButton.target = self
        settingsButton.action = #selector(permissionAction)
        requestButton.target = self
        requestButton.action = #selector(requestPermissionAction)
        setupButton.target = self
        setupButton.action = #selector(setupAction)
        let actions = NSStackView(views: [picker, goButton, stopButton])
        actions.orientation = .horizontal
        actions.spacing = 10
        picker.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let maintenance = NSStackView(views: [setupButton, requestButton, settingsButton])
        maintenance.orientation = .horizontal
        maintenance.spacing = 10
        progressBar.style = .bar
        progressBar.isIndeterminate = false
        progressBar.minValue = 0
        progressBar.maxValue = 6
        progressStack = NSStackView(views: [progressLabel, progressBar])
        progressStack.orientation = .vertical
        progressStack.alignment = .leading
        progressStack.spacing = 6
        progressStack.isHidden = true
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        outputView.isEditable = false
        outputView.isSelectable = true
        outputView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        outputView.textContainerInset = NSSize(width: 10, height: 10)
        outputView.isVerticallyResizable = true
        outputView.isHorizontallyResizable = false
        outputView.autoresizingMask = [.width]
        outputView.textContainer?.widthTracksTextView = true
        scroll.documentView = outputView
        let stack = NSStackView(views: [title, stateLabel, watcherLabel, permissionLabel,
                                      actions, maintenance, progressStack, scroll])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = window.contentView!
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20),
            actions.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll.widthAnchor.constraint(equalTo: stack.widthAnchor),
            scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 170),
            progressStack.widthAnchor.constraint(equalTo: stack.widthAnchor),
            progressBar.widthAnchor.constraint(equalTo: progressStack.widthAnchor)
        ])
        refreshControls()
    }

    private var selectedAction: BotAction {
        BotAction(rawValue: picker.titleOfSelectedItem ?? "") ?? .check
    }

    private func refreshControls() {
        let busy = busyCount > 0 || workerStarting
        let choice = selectedAction
        let usableDuringSetup: [BotAction] = [.requestPermission, .permission, .diagnostics, .quit]
        goButton.isEnabled = setupActive ? usableDuringSetup.contains(choice)
            : (!busy || choice == .stop || choice == .permission || choice == .requestPermission)
        if choice == .setup && (watcherRunning || workerProcess != nil || workerStarting) { goButton.isEnabled = false }
        if [BotAction.dryTest, .startTest, .dryRoster, .startRoster].contains(choice)
            && (watcherRunning || workerProcess != nil || workerStarting) { goButton.isEnabled = false }
        stopButton.isEnabled = !setupActive
        setupButton.isEnabled = !setupActive && !busy && !watcherRunning && workerProcess == nil
        setupButton.title = state == "NOT_INSTALLED" ? "Set up" : "Update / Repair"
        settingsButton.isEnabled = true
        requestButton.isEnabled = true
        let trusted = AXIsProcessTrusted()
        permissionLabel.stringValue = "App Accessibility: \(trusted ? "allowed" : "not granted")  ·  Helper: \(helperPermission)"
        progressStack.isHidden = !setupActive
        if !setupActive {
            progressLabel.stringValue = ""
            progressBar.doubleValue = 0
        }
    }

    private func showOutput(_ text: String) {
        outputView.string = text
        outputView.scrollRangeToVisible(NSRange(location: 0, length: 0))
    }

    private func display(_ result: BackendResult, operation: String) {
        let text = result.output.isEmpty ? "\(operation) finished." : result.output
        showOutput(result.code == 0 ? text : "\(operation) did not finish (exit \(result.code)).\n\n\(text)")
    }

    private func run(_ command: String, extra: [String] = [], displayResult: Bool = true,
                     completion: ((BackendResult) -> Void)? = nil) {
        busyCount += 1
        refreshControls()
        backend.asynchronously([command] + extra) { [weak self] result in
            guard let self = self else { return }
            self.busyCount -= 1
            if displayResult { self.display(result, operation: command) }
            completion?(result)
            self.refreshControls()
            self.poll()
        }
    }

    private func poll() {
        guard !polling else { return }
        polling = true
        let generation = pollGeneration
        let wasSettingUp = setupActive
        DispatchQueue.global(qos: .utility).async {
            let initial = self.backend.call(["state"])
            var current = initial.output
            var progress: BackendResult?
            var details: BackendResult?
            var status: BackendResult?
            if initial.code == 0 && (current == "SETTING_UP" || wasSettingUp) {
                progress = self.backend.call(["progress"])
                if progress?.output.hasPrefix("DONE") == true {
                    details = self.backend.call([progress?.output == "DONE 0" ? "log" : "error"])
                    current = self.backend.call(["state"]).output
                }
            }
            if initial.code == 0 && (current == "READY" || current == "UPDATE_AVAILABLE") {
                status = self.backend.call(["status"])
            }
            DispatchQueue.main.async {
                self.polling = false
                guard generation == self.pollGeneration else { self.poll(); return }
                if initial.code != 0 {
                    self.stateLabel.stringValue = "Installation status could not be checked."
                    if self.reportedPollError != initial.output {
                        self.reportedPollError = initial.output
                        self.display(initial, operation: "Installation status")
                    }
                    self.refreshControls()
                    return
                }
                self.reportedPollError = ""
                self.state = current
                let finished = progress?.output.hasPrefix("DONE") == true
                self.setupActive = current == "SETTING_UP" && !finished
                switch current {
                case "READY": self.stateLabel.stringValue = "Installation: ready"
                case "UPDATE_AVAILABLE": self.stateLabel.stringValue = "Installation: an update is available"
                case "NOT_INSTALLED": self.stateLabel.stringValue = "Installation: set up is required"
                case "SETTING_UP": self.stateLabel.stringValue = self.setupActive ? "Installation: setting up…" : "Installation: setup finished"
                default: self.stateLabel.stringValue = "Installation: \(current)"
                }
                if self.setupActive {
                    let text = progress?.output ?? "Starting…"
                    self.progressLabel.stringValue = text
                    self.progressBar.doubleValue = Double(text.split(separator: "/").first.flatMap { Int($0) } ?? 0)
                    self.watcherLabel.stringValue = "Watcher: unavailable during setup"
                } else if let result = status {
                    self.watcherRunning = result.code == 0 && result.output.hasPrefix("ON")
                    if self.watcherRunning { self.workerStarting = false }
                    self.watcherLabel.stringValue = result.code == 0
                        ? "Watcher: \(result.output.components(separatedBy: .newlines).first ?? "unknown")"
                        : "Watcher: status check failed (see Diagnostics)"
                } else {
                    self.watcherLabel.stringValue = "Watcher: setup required"
                }
                if self.stopRequested && self.watcherRunning && !self.stopInFlight { self.issueStop() }
                if finished && wasSettingUp {
                    let success = progress?.output == "DONE 0"
                    self.showOutput((success ? "Setup finished.\n\n" : "Setup did not finish.\n\n")
                                    + (details?.output ?? "No diagnostic was recorded.")
                                    + "\n\nFull setup log: \(self.paths.home.path)/logs/setup.log")
                }
                self.refreshControls()
            }
        }
    }

    private func requireHostPermission() -> Bool {
        guard AXIsProcessTrusted() else {
            showOutput("War Room Bot does not have Accessibility permission. Click Accessibility Settings, allow this app, then reopen it. Diagnostics reports the bundled helper's permission separately.")
            refreshControls()
            return false
        }
        return true
    }

    private func withWatcherPermission(generation: Int, _ continuation: @escaping () -> Void) {
        guard requireHostPermission() else { return }
        run("trusted", displayResult: false) { [weak self] result in
            guard let self = self else { return }
            guard generation == self.actionGeneration else { return }
            let trusted = result.code == 0 && result.output.trimmingCharacters(in: .whitespacesAndNewlines) == "yes"
            self.helperPermission = trusted ? "allowed at last check" : "not granted at last check"
            guard trusted else {
                self.showOutput("The app has Accessibility permission, but its bundled helper has not confirmed permission. Open Accessibility Settings to review access, then use Diagnostics.\n\nHelper check (exit \(result.code)):\n\(result.output)")
                return
            }
            continuation()
        }
    }

    private func startWorker(_ command: String, generation: Int) {
        guard generation == actionGeneration else { return }
        guard workerProcess == nil && !workerStarting else {
            showOutput("This app already has a watcher running. Choose Stop before starting another.")
            return
        }
        workerStarting = true
        workerGeneration += 1
        let sessionGeneration = workerGeneration
        refreshControls()
        showOutput("Starting the watcher…\nIts output is written to \(paths.home.path)/logs/watcher.log. Keep this app running; closing the window hides it while watching.")
        do {
            workerProcess = try backend.launchWatcher(command) { [weak self] result in
                guard let self = self else { return }
                guard sessionGeneration == self.workerGeneration else { return }
                self.workerProcess = nil
                self.workerStarting = false
                self.watcherRunning = false
                self.stopRequested = false
                self.cancellationTimer?.invalidate()
                self.cancellationTimer = nil
                self.display(BackendResult(code: result.code,
                    output: (result.output.isEmpty ? "Watcher stopped." : result.output)
                        + "\n\nWatcher log: \(self.paths.home.path)/logs/watcher.log"), operation: "Watcher")
                self.refreshControls()
                if self.quitAfterWorkerStops && result.code == 0 {
                    self.quitApproved = true
                    NSApp.terminate(nil)
                } else {
                    self.quitAfterWorkerStops = false
                    self.quitWaitsForOwnedCompletion = false
                    self.poll()
                }
            }
            poll()
        } catch {
            workerStarting = false
            workerProcess = nil
            showOutput("Could not start the watcher: \(error.localizedDescription)")
            refreshControls()
        }
    }

    private func confirm(_ title: String, detail: String, accept: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail
        alert.alertStyle = .warning
        alert.addButton(withTitle: accept)
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    @objc private func selectionChanged() { refreshControls() }
    @objc private func goAction() { perform(selectedAction) }
    @objc private func stopAction() { perform(.stop) }
    @objc private func setupAction() { perform(.setup) }
    @objc private func permissionAction() { perform(.permission) }
    @objc private func requestPermissionAction() { perform(.requestPermission) }
    @objc private func quitAction() { NSApp.terminate(nil) }
    @objc private func openWindowAction() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    @objc private func stopAndQuitAction() { stopAndQuit() }

    private func perform(_ action: BotAction) {
        if setupActive && ![BotAction.requestPermission, .permission, .diagnostics, .quit].contains(action) { return }
        if (busyCount > 0 || workerStarting) && ![BotAction.stop, .requestPermission, .permission, .quit].contains(action) { return }
        let generation = actionGeneration
        switch action {
        case .check: run("check")
        case .dryTest:
            withWatcherPermission(generation: generation) { [weak self] in self?.startWorker("dry", generation: generation) }
        case .startTest:
            withWatcherPermission(generation: generation) { [weak self] in
                self?.run("number", displayResult: false) { [weak self] result in
                guard let self = self else { return }
                guard generation == self.actionGeneration else { return }
                guard result.code == 0 && !result.output.isEmpty else {
                    self.showOutput("Set your test phone number first with Change test phone number.\n\n\(result.output)")
                    return
                }
                if self.confirm("Start watching in test mode?",
                                detail: "Each new visitor can trigger a spoken welcome and a call to your test number:\n\n\(result.output)\n\nKeep Zoom in the bridge meeting and this Mac awake and unlocked.", accept: "Start test mode") {
                    self.startWorker("start", generation: generation)
                }
                }
            }
        case .previewRoster: run("roster-preview")
        case .dryRoster:
            withWatcherPermission(generation: generation) { [weak self] in
                self?.run("roster-preview") { [weak self] result in
                    if result.code == 0 { self?.startWorker("roster-dry", generation: generation) }
                }
            }
        case .startRoster:
            withWatcherPermission(generation: generation) { [weak self] in
                self?.run("roster-preview") { [weak self] result in
                guard let self = self, result.code == 0, !result.output.isEmpty else { return }
                guard generation == self.actionGeneration else { return }
                if self.confirm("Start live roster calls?",
                                detail: "New visitors can trigger real calls to the on-duty engineers in your roster. The current roster selection is:\n\n\(result.output)\n\nThe on-duty selection follows your roster as shifts change. Review the phone numbers before starting.", accept: "Start roster calls") {
                    self.startWorker("roster-start", generation: generation)
                }
                }
            }
        case .stop: stopWatcher()
        case .status: run("status")
        case .recent: run("recent")
        case .changeNumber: changeNumber()
        case .openData:
            if !NSWorkspace.shared.open(paths.home) { showOutput("Could not open \(paths.home.path). Set up may be required.") }
        case .setup:
            guard confirm(state == "NOT_INSTALLED" ? "Set up War Room Bot?" : "Update or repair War Room Bot?",
                          detail: "Program files and packages will be installed in \(paths.home.path). Your settings, roster and logs are kept. Connect to the Equinix network or VPN.", accept: "Run setup") else { return }
            pollGeneration += 1
            run("setup-bg") { [weak self] result in
                guard let self = self else { return }
                self.setupActive = result.code == 0
                self.progressLabel.stringValue = result.code == 0 ? "Starting…" : ""
                self.progressBar.doubleValue = 0
                self.refreshControls()
            }
        case .requestPermission:
            // This explicit user action is the sole place that requests permission.
            if !AXIsProcessTrusted() {
                let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
                _ = AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
            }
            run("permission-status")
        case .permission:
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
            run("permission-status")
        case .diagnostics: diagnostics()
        case .quit: NSApp.terminate(nil)
        }
    }

    private func changeNumber() {
        run("number", displayResult: false) { [weak self] result in
            guard let self = self else { return }
            let alert = NSAlert()
            alert.messageText = "Change test phone number"
            alert.informativeText = "Use + and the country code, for example +14155550123. Test mode calls only this number."
            alert.addButton(withTitle: "Save")
            alert.addButton(withTitle: "Cancel")
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 330, height: 24))
            field.stringValue = result.code == 0 && !result.output.isEmpty ? result.output : "+"
            alert.accessoryView = field
            alert.window.initialFirstResponder = field
            if alert.runModal() == .alertFirstButtonReturn { self.run("set-number", extra: [field.stringValue]) }
        }
    }

    private func diagnostics() {
        busyCount += 1
        refreshControls()
        let host = AXIsProcessTrusted() ? "allowed" : "not granted"
        DispatchQueue.global(qos: .userInitiated).async {
            let permission = self.backend.call(["permission-status"])
            let status = self.backend.call(["status"])
            let log = self.backend.call(["log", "40"])
            let watcherLog = CommandCapture.tail(of: self.paths.home.appendingPathComponent("logs/watcher.log"))
                .components(separatedBy: .newlines).suffix(40).joined(separator: "\n")
            DispatchQueue.main.async {
                self.busyCount -= 1
                self.showOutput("Version: \(self.paths.version)\nBundle ID: \(Bundle.main.bundleIdentifier ?? "missing")\nNative executable: \(Bundle.main.executableURL?.path ?? "missing")\nApp Accessibility: \(host)\nBundled helper: \(self.paths.helper.path)\nData: \(self.paths.home.path)\n\nHelper permission check (exit \(permission.code)):\n\(permission.output)\n\nWatcher status (exit \(status.code)):\n\(status.output)\n\nRecent setup log:\n\(log.output)\n\nRecent watcher log:\n\(watcherLog)")
                self.refreshControls()
            }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if watcherRunning || workerStarting || workerProcess != nil {
            window.orderOut(nil)
            return false
        }
        NSApp.terminate(nil)
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitApproved { return .terminateNow }
        if setupActive {
            return confirm("Quit while setup continues?", detail: "Setup keeps running in the background. Open War Room Bot again to see its result.", accept: "Quit")
                ? .terminateNow : .terminateCancel
        }
        if watcherRunning || workerStarting || workerProcess != nil {
            let alert = NSAlert()
            alert.messageText = "The watcher is running"
            alert.informativeText = "Keep this app running while the watcher uses its bundled helper. You can hide its window, or stop the watcher and quit."
            alert.addButton(withTitle: "Stop and quit")
            alert.addButton(withTitle: "Hide and keep watching")
            alert.addButton(withTitle: "Cancel")
            switch alert.runModal() {
            case .alertFirstButtonReturn:
                stopAndQuit()
                return .terminateCancel
            case .alertSecondButtonReturn: window.orderOut(nil); return .terminateCancel
            default: return .terminateCancel
            }
        }
        return .terminateNow
    }

    private func stopAndQuit() {
        if setupActive {
            showOutput("Setup is running. Use Quit to choose whether to leave setup running in the background.")
            openWindowAction()
            return
        }
        quitAfterWorkerStops = true
        quitWaitsForOwnedCompletion = workerProcess != nil || workerStarting
        stopWatcher()
    }

    private func stopWatcher() {
        actionGeneration += 1 // Cancels permission/number/roster callbacks and post-confirm starts.
        stopRequested = true
        // Before registration there is no nonce record yet. This Process object
        // still identifies our own live child exactly. Retry while its shell or
        // interpreter is starting; after registration use the validated backend.
        if workerStarting, let task = workerProcess, task.isRunning { task.interrupt() }
        if workerProcess?.isRunning == true && cancellationTimer == nil {
            cancellationTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
                guard let self = self, self.stopRequested, let task = self.workerProcess, task.isRunning else {
                    timer.invalidate()
                    self?.cancellationTimer = nil
                    return
                }
                if self.workerStarting { task.interrupt() }
                else if self.watcherRunning && !self.stopInFlight { self.issueStop() }
            }
        }
        if !stopInFlight { issueStop() }
    }

    private func issueStop() {
        stopInFlight = true
        run("stop", displayResult: false) { [weak self] result in
            guard let self = self else { return }
            self.stopInFlight = false
            let ownedChildAlive = self.workerStarting || self.workerProcess != nil
            if ownedChildAlive && result.code == 0 {
                self.showOutput("Stop requested. Waiting for this app's watcher process to exit.\n\n\(result.output)")
            } else { self.display(result, operation: "Stop") }
            if result.code == 0 && !ownedChildAlive {
                self.stopRequested = false
                if self.quitAfterWorkerStops && !self.quitWaitsForOwnedCompletion {
                    self.run("status", displayResult: false) { [weak self] status in
                        guard let self = self, self.quitAfterWorkerStops, !self.quitWaitsForOwnedCompletion,
                              self.workerProcess == nil, !self.workerStarting else { return }
                        if status.code == 0 && status.output.hasPrefix("OFF") {
                            self.quitApproved = true
                            NSApp.terminate(nil)
                        } else {
                            self.quitAfterWorkerStops = false
                            self.display(status, operation: "Shutdown status")
                            self.openWindowAction()
                        }
                    }
                }
            } else if result.code != 0 && result.code != 25 {
                self.quitAfterWorkerStops = false
                self.openWindowAction()
            }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWindowAction()
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        cancellationTimer?.invalidate()
    }
}

let appPaths = AppPaths()
if ProcessInfo.processInfo.arguments.contains("--smoke-test") { exit(appPaths.smokeTest()) }
let application = NSApplication.shared
application.setActivationPolicy(.regular)
let delegate = AppDelegate(paths: appPaths)
application.delegate = delegate
application.run()
