[app]
title = 局域网程序分享
package.name = lancodeshare
package.domain = org.tju.challenge
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,md,txt,java,ttf,ttc,json
source.exclude_dirs = __pycache__,.buildozer,bin
version = 1.3
requirements = python3,kivy,pyjnius,plyer,pygments,qrcode,pillow
icon.filename = assets/icon.png
orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO
android.api = 35
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.add_src = android_src

[buildozer]
log_level = 2
warn_on_root = 1

android.numeric_version = 13
