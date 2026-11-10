# Simple Build

CLI builder for existing Minecraft Forge and Fabric Gradle mod projects on Windows.

## Install

Run `install.bat`. Requires **Python 3.9+**.

## Commands

Go to the mod's root folder and execute:

```cmd
simple-build start
```

- `simple-build start`: choose Forge or Fabric, then Minecraft version; check project metadata; download matching Java if necessary; run the existing Gradle build; copy resulting JARs to `output`.
- `simple-build cache`: display the total disk size and path of the cache, plus the clear command.
- `simple-build clear`: ask for confirmation and delete the tool's cache (downloaded JDKs, Gradle distributions, and the isolated Gradle dependency cache). The next build downloads dependencies again.

Cache directory: `%LOCALAPPDATA%\simple-build\cache`. Gradle runs with an isolated `GRADLE_USER_HOME` there; it does not use or delete your normal `~/.gradle` cache. Project-local `.gradle` and `build` directories are not included in the cache size and are never cleared by this command.
