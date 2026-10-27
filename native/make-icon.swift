// Original Codex Lookout artwork, MIT. Run: swift native/make-icon.swift
import AppKit
import Foundation

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let resources = root.appendingPathComponent("native/Resources")
let assets = root.appendingPathComponent("docs/assets")
try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
try FileManager.default.createDirectory(at: assets, withIntermediateDirectories: true)
let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
NSColor(calibratedRed: 0.09, green: 0.17, blue: 0.23, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 48, y: 48, width: 928, height: 928), xRadius: 208, yRadius: 208).fill()
NSColor(calibratedRed: 0.93, green: 0.97, blue: 0.95, alpha: 1).setStroke()
let frame = NSBezierPath(roundedRect: NSRect(x: 225, y: 275, width: 574, height: 474), xRadius: 76, yRadius: 76)
frame.lineWidth = 42
frame.stroke()
NSColor(calibratedRed: 0.93, green: 0.97, blue: 0.95, alpha: 1).setFill()
for (x, height) in [(335.0, 116.0), (445.0, 216.0), (555.0, 164.0)] {
    NSBezierPath(roundedRect: NSRect(x: x, y: 390, width: 44, height: height), xRadius: 22, yRadius: 22).fill()
}
NSColor(calibratedRed: 0.09, green: 0.17, blue: 0.23, alpha: 1).setFill()
NSBezierPath(ovalIn: NSRect(x: 650, y: 614, width: 224, height: 224)).fill()
NSColor(calibratedRed: 0.48, green: 0.89, blue: 0.70, alpha: 1).setFill()
NSBezierPath(ovalIn: NSRect(x: 684, y: 648, width: 156, height: 156)).fill()
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
let png = bitmap.representation(using: .png, properties: [:])!
try png.write(to: resources.appendingPathComponent("AppIcon.png"))
try png.write(to: assets.appendingPathComponent("icon.png"))
print("Wrote original Lookout icon")
