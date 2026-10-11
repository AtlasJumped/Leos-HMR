#!/usr/bin/env python3
"""Wallpaper driver interface (DESIGN.md §7). Driver #1: Smart Video Wallpaper Reborn.

The interface is deliberately thin — apply_video / apply_image / lockscreen — so a fallback
engine (waywallen) is a driver swap, not a redesign. Screens are matched by GEOMETRY, never
by index (containment order is not stable).

[TEST] on machine: the evaluateScript write, the kscreenlockerrc nested group keys, and
NVDEC active (nvidia-smi dmon dec% > 0) are week-1 soak items before bulk asset generation.
"""
import json
import os
import subprocess

STACK = os.environ.get("ALETHEON_STACK", "/blazing/stack")
SVWR = "luisbocanegra.smart.video.wallpaper.reborn"
IMAGE = "org.kde.image"

# PauseMode (verified from plugin main.xml): 0=maximized/fullscreen window present,
# 1=active window, 2=any visible window, 3=never pause.
PAUSE = {"full": 3, "low": 0}


def screens():
    """state/screens.json maps logical names to geometry origins, e.g.
    {"dp3": {"x": 0, "y": 1440}, "dp1": {"x": 3440, "y": 1440}, "dp2": {"x": 1699, "y": 0}}"""
    with open(os.path.join(STACK, "state", "screens.json")) as f:
        return json.load(f)


def _evaluate(script):
    r = subprocess.run(
        ["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
         "org.kde.PlasmaShell.evaluateScript", script],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"evaluateScript failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def _desktop_js(x, y, body):
    # Match the containment whose screenGeometry origin equals (x, y).
    return (
        "for (var k in desktops()) { var d = desktops()[k];"
        " if (d.screen < 0) continue; var g = screenGeometry(d.screen);"
        f" if (g.x == {int(x)} && g.y == {int(y)}) {{ {body} }} }}"
    )


def apply_video(screen, video_path, pause_mode=3, crossfade=True):
    geo = screens()[screen]
    urls = json.dumps([{"filename": "file://" + video_path, "enabled": True,
                        "duration": 0, "customDuration": 0, "loop": True}])
    body = (
        f'd.wallpaperPlugin = "{SVWR}";'
        f'd.currentConfigGroup = ["Wallpaper", "{SVWR}", "General"];'
        f'd.writeConfig("VideoUrls", {json.dumps(urls)});'
        f'd.writeConfig("PauseMode", {int(pause_mode)});'
        f'd.writeConfig("CrossfadeEnabled", {str(bool(crossfade)).lower()});'
    )
    _evaluate(_desktop_js(geo["x"], geo["y"], body))


def apply_image(screen, image_path):
    geo = screens()[screen]
    body = (
        f'd.wallpaperPlugin = "{IMAGE}";'
        f'd.currentConfigGroup = ["Wallpaper", "{IMAGE}", "General"];'
        f'd.writeConfig("Image", {json.dumps("file://" + image_path)});'
    )
    _evaluate(_desktop_js(geo["x"], geo["y"], body))


def read_back(screen):
    """Post-apply verification (§7 'transactional-ish'): read one key back."""
    geo = screens()[screen]
    body = (
        f'd.currentConfigGroup = ["Wallpaper", "{SVWR}", "General"];'
        'print(d.readConfig("VideoUrls"));'
    )
    try:
        return _evaluate(_desktop_js(geo["x"], geo["y"], body)).strip()
    except RuntimeError:
        return ""


def lockscreen_video(video_path):
    urls = json.dumps([{"filename": "file://" + video_path, "enabled": True,
                        "duration": 0, "customDuration": 0, "loop": True}])
    subprocess.run(["kwriteconfig6", "--file", "kscreenlockerrc",
                    "--group", "Greeter", "--key", "WallpaperPlugin", SVWR], check=True)
    subprocess.run(["kwriteconfig6", "--file", "kscreenlockerrc",
                    "--group", "Greeter", "--group", "Wallpaper", "--group", SVWR,
                    "--group", "General", "--key", "VideoUrls", urls], check=True)


def lockscreen_image(image_path):
    subprocess.run(["kwriteconfig6", "--file", "kscreenlockerrc",
                    "--group", "Greeter", "--key", "WallpaperPlugin", IMAGE], check=True)
    subprocess.run(["kwriteconfig6", "--file", "kscreenlockerrc",
                    "--group", "Greeter", "--group", "Wallpaper", "--group", IMAGE,
                    "--group", "General", "--key", "Image", "file://" + image_path],
                   check=True)


def plasmashell_active():
    r = subprocess.run(["systemctl", "--user", "is-active", "plasma-plasmashell.service"],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def outputs_up(expected=3):
    """Refuse wallpaper writes while outputs are down (fx away) — geometry matching
    would target the wrong containments (§5)."""
    r = subprocess.run(["kscreen-doctor", "-o"], capture_output=True, text=True)
    return r.stdout.count("enabled") >= expected
