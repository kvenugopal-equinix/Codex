// axctl: small accessibility helper for the Zoom macOS client. All output is one JSON object.
// Build: tools/build_axctl.sh        Needs Accessibility permission for the app that runs it.
//
// Commands:  trusted | prompt | windows | texts | find | press | click | set | get | close | inspect | activate | participants
//            (prompt = trusted, but also asks macOS to list the calling app under Accessibility and shows its allow dialog)
// Options:   --window RE  --role AXRole  --match RE  --not RE  --field any|title|desc|value
//            --index N  --value TEXT  --depth N
import Cocoa
import ApplicationServices

func attr(_ el: AXUIElement, _ name: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, name as CFString, &v) == .success ? (v as AnyObject?) : nil
}
func str(_ el: AXUIElement, _ name: String) -> String {
    if let s = attr(el, name) as? String { return s }
    if let n = attr(el, name) as? NSNumber { return n.stringValue }
    return ""
}
func out(_ obj: [String: Any]) -> Never {
    let d = try! JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
    print(String(data: d, encoding: .utf8)!)
    exit(obj["ok"] as? Bool == false ? 2 : 0)
}
func fail(_ msg: String) -> Never { out(["ok": false, "error": msg]) }

var opts: [String: String] = [:]
let argv = Array(CommandLine.arguments.dropFirst())
guard let cmd = argv.first else { fail("no command") }
var i = 1
while i < argv.count {
    if argv[i].hasPrefix("--"), i + 1 < argv.count { opts[String(argv[i].dropFirst(2))] = argv[i + 1]; i += 2 } else { i += 1 }
}
if cmd == "trusted" { out(["ok": AXIsProcessTrusted()]) }
if cmd == "prompt" {
    // "ok" means the prompt was issued, not that access was granted: read "trusted" for that.
    let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
    out(["ok": true, "trusted": AXIsProcessTrustedWithOptions([key: true] as CFDictionary)])
}
guard AXIsProcessTrusted() else { fail("not trusted: this app has no Accessibility permission") }
guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "us.zoom.xos").first else { fail("zoom.us is not running") }
let root = AXUIElementCreateApplication(app.processIdentifier)
AXUIElementSetMessagingTimeout(root, 3)
let maxDepth = Int(opts["depth"] ?? "") ?? 14

func rx(_ p: String?) -> NSRegularExpression? {
    guard let p = p, !p.isEmpty else { return nil }
    guard let r = try? NSRegularExpression(pattern: p, options: [.caseInsensitive]) else { fail("bad regex: \(p)") }
    return r
}
func hit(_ r: NSRegularExpression?, _ s: String) -> Bool {
    guard let r = r else { return true }
    return r.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
}
let winRx = rx(opts["window"])
let matchRx = rx(opts["match"]), notRx = rx(opts["not"])
let field = opts["field"] ?? "any"

struct Node { let el: AXUIElement; let window: String; let role, title, desc, value, id: String }

func exposedWindows() -> [AXUIElement] {
    var found: [AXUIElement] = []
    func append(_ window: AXUIElement) {
        if !found.contains(where: { CFEqual($0, window) }) { found.append(window) }
    }
    for window in (attr(root, "AXWindows") as? [AXUIElement]) ?? [] { append(window) }
    // Some Zoom states omit a window from AXWindows but still expose its direct reference.
    for name in ["AXMainWindow", "AXFocusedWindow"] {
        if let value = attr(root, name), CFGetTypeID(value) == AXUIElementGetTypeID() {
            append(value as! AXUIElement)
        }
    }
    for child in (attr(root, "AXChildren") as? [AXUIElement]) ?? [] {
        if str(child, "AXRole") == "AXWindow" { append(child) }
    }
    return found
}

func windows() -> [(AXUIElement, String)] {
    let ws = exposedWindows()
    return ws.map { ($0, str($0, "AXTitle")) }.filter { w in
        winRx != nil ? hit(winRx, w.1) : w.1 != "Zoom Workplace"   // Workplace is huge and rarely needed
    }
}
func collect(_ el: AXUIElement, _ window: String, _ d: Int, _ acc: inout [Node]) {
    if d > maxDepth { return }
    let role = str(el, "AXRole")
    acc.append(Node(el: el, window: window, role: role, title: str(el, "AXTitle"), desc: str(el, "AXDescription"),
                    value: String(str(el, "AXValue").prefix(300)), id: str(el, "AXIdentifier")))
    if role == "AXTable" { return }
    for k in (attr(el, "AXChildren") as? [AXUIElement]) ?? [] { collect(k, window, d + 1, &acc) }
}
func allNodes() -> [Node] {
    var acc: [Node] = []
    for (w, name) in windows() { collect(w, name, 0, &acc) }
    return acc
}
func fields(_ n: Node) -> [String] {
    switch field { case "title": return [n.title]; case "desc": return [n.desc]; case "value": return [n.value]
    default: return [n.title, n.desc, n.value] }
}
func selected(_ nodes: [Node]) -> [Node] {
    nodes.filter { n in
        if let r = opts["role"], n.role != r { return false }
        let f = fields(n)
        if notRx != nil, f.contains(where: { hit(notRx, $0) && !$0.isEmpty }) { return false }
        if matchRx != nil { return f.contains(where: { !$0.isEmpty && hit(matchRx, $0) }) }
        return true
    }
}
func describe(_ n: Node) -> [String: Any] {
    ["window": n.window, "role": n.role, "title": n.title, "desc": n.desc, "value": n.value, "id": n.id,
     "enabled": (attr(n.el, "AXEnabled") as? NSNumber)?.boolValue ?? true]
}
func pick(_ nodes: [Node]) -> Node {
    let m = selected(nodes)
    let idx = Int(opts["index"] ?? "") ?? 0
    guard idx >= 0 && idx < m.count else { fail("not found (\(m.count) matches)") }
    return m[idx]
}

switch cmd {
case "windows":
    out(["ok": true, "windows": exposedWindows().map { str($0, "AXTitle") }])
case "texts":
    out(["ok": true, "nodes": allNodes().filter { !($0.title.isEmpty && $0.desc.isEmpty && $0.value.isEmpty) }.map(describe)])
case "find":
    out(["ok": true, "matches": selected(allNodes()).map(describe)])
case "press":
    let n = pick(allNodes())
    if (attr(n.el, "AXEnabled") as? NSNumber)?.boolValue == false { fail("element is disabled") }
    let r = AXUIElementPerformAction(n.el, kAXPressAction as CFString)
    if r != .success { fail("press failed: \(r.rawValue)") }
    out(["ok": true, "pressed": describe(n)])
case "click":
    // A real mouse click at the element's centre, for controls that expose no AXPress action (Zoom's share tab).
    // The pointer is put back where it was afterwards.
    let n = pick(allNodes())
    guard let pv = attr(n.el, "AXPosition"), let sv = attr(n.el, "AXSize") else { fail("element has no position") }
    var p = CGPoint.zero, sz = CGSize.zero
    guard AXValueGetValue(pv as! AXValue, .cgPoint, &p), AXValueGetValue(sv as! AXValue, .cgSize, &sz), sz.width > 0, sz.height > 0 else {
        fail("element has no size")
    }
    let at = CGPoint(x: p.x + sz.width / 2, y: p.y + sz.height / 2)
    let was = CGEvent(source: nil)?.location ?? at
    for (type, button) in [(CGEventType.mouseMoved, CGMouseButton.left), (.leftMouseDown, .left), (.leftMouseUp, .left)] {
        CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: at, mouseButton: button)?.post(tap: .cghidEventTap)
        Thread.sleep(forTimeInterval: 0.08)
    }
    CGWarpMouseCursorPosition(was)
    out(["ok": true, "clicked": describe(n), "at": [Double(at.x), Double(at.y)]])
case "set":
    guard let v = opts["value"] else { fail("--value required") }
    let n = pick(allNodes())
    _ = AXUIElementSetAttributeValue(n.el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    let r = AXUIElementSetAttributeValue(n.el, kAXValueAttribute as CFString, v as CFTypeRef)
    if r != .success { fail("set failed: \(r.rawValue)") }
    out(["ok": true, "value": str(n.el, "AXValue")])   // always read back
case "get":
    out(["ok": true, "value": str(pick(allNodes()).el, "AXValue")])
case "inspect":
    let n = pick(allNodes())
    var names: CFArray?
    AXUIElementCopyActionNames(n.el, &names)
    func pt(_ a: String) -> [Double]? {
        guard let v = attr(n.el, a) else { return nil }
        var p = CGPoint.zero, sz = CGSize.zero
        if AXValueGetValue(v as! AXValue, .cgPoint, &p) { return [Double(p.x), Double(p.y)] }
        if AXValueGetValue(v as! AXValue, .cgSize, &sz) { return [Double(sz.width), Double(sz.height)] }
        return nil
    }
    var info = describe(n)
    info["actions"] = (names as? [String]) ?? []
    info["position"] = pt("AXPosition") ?? []
    info["size"] = pt("AXSize") ?? []
    info["focused"] = (attr(n.el, "AXFocused") as? NSNumber)?.boolValue ?? false
    info["zoom_frontmost"] = app.isActive
    let wins = exposedWindows()
    info["windows_main"] = wins.map { "\(str($0, "AXTitle")): main=\(str($0, "AXMain")) min=\(str($0, "AXMinimized"))" }
    out(["ok": true, "inspect": info])
case "activate":
    let ok = AXUIElementSetAttributeValue(root, "AXFrontmost" as CFString, kCFBooleanTrue) == .success
    if let (w, _) = windows().first { _ = AXUIElementPerformAction(w, kAXRaiseAction as CFString) }
    Thread.sleep(forTimeInterval: 0.4)
    out(["ok": ok, "zoom_frontmost": app.isActive])
case "close":
    guard winRx != nil, let (w, name) = windows().first else { fail("no window matches --window") }
    guard let raw = attr(w, "AXCloseButton") else { fail("window has no close button") }
    let r = AXUIElementPerformAction(raw as! AXUIElement, kAXPressAction as CFString)
    if r != .success { fail("close failed: \(r.rawValue)") }
    out(["ok": true, "closed": name])
case "participants":
    // The list lives in the main window when the panel is docked, but in its own "Participants (N)" window
    // when the meeting is full screen or the panel is popped out, so search both.
    var acc: [Node] = [], listWins = 0
    var haveMeeting = false
    for (w, name) in windows() {
        if str(w, "AXIdentifier") == "zm.meeting.window.main" { haveMeeting = true; collect(w, name, 0, &acc) }
        else if name.range(of: "^Participants( \\(\\d+\\))?$", options: .regularExpression) != nil { listWins += 1; collect(w, name, 0, &acc) }
    }
    if !haveMeeting && listWins == 0 { fail("no meeting or Participants window") }
    let panel = acc.first { $0.id == "participant" }?.desc ?? ""
    var outlines: [Node] = []
    for node in acc where node.role == "AXOutline" && node.desc == "Participants list" {
        if !outlines.contains(where: { CFEqual($0.el, node.el) }) { outlines.append(node) }
    }
    if outlines.count > 1 { fail("multiple Participants lists are visible; close the extra meeting panels") }
    guard let outline = outlines.first else {
        out(["ok": false, "error": "participants list not visible", "panel_button": panel, "list_windows": listWins])
    }
    var names: [String] = []
    for row in (attr(outline.el, "AXChildren") as? [AXUIElement]) ?? [] {
        var sub: [Node] = []
        collect(row, "", 0, &sub)
        if let t = sub.first(where: { $0.role == "AXStaticText" && !$0.value.isEmpty }) { names.append(t.value) }
    }
    out(["ok": true, "participants": names, "panel_button": panel, "source_window": outline.window])
default:
    fail("unknown command \(cmd)")
}
