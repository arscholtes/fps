#!/usr/bin/env swift
// Screen geometry for FPS window placement.
//
// Two coordinate spaces meet here and disagree. NSScreen puts the origin at the
// BOTTOM-left of the main screen with y increasing upward; AppleScript puts it at
// the TOP-left with y increasing downward. A window placed with unconverted
// coordinates lands off-screen and nothing errors — it just looks wrong, on the
// multi-monitor setup nobody tested.
//
// Emits tab-separated: index, x, y, w, h, isMain — already in AppleScript space.
import AppKit

guard let main = NSScreen.screens.first(where: { $0 == NSScreen.main }) ?? NSScreen.screens.first else {
    exit(1)
}
let mainTop = main.frame.origin.y + main.frame.height

for (i, s) in NSScreen.screens.enumerated() {
    let f = s.frame
    // Flip: distance from the main screen's top edge down to this screen's top edge.
    let appleY = mainTop - (f.origin.y + f.height)
    let flag = (s == NSScreen.main) ? "MAIN" : "-"
    print("\(i)\t\(Int(f.origin.x))\t\(Int(appleY))\t\(Int(f.width))\t\(Int(f.height))\t\(flag)")
}
