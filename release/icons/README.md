# Release icon assets

Base64 keeps the binary icons as text; packaging decodes them into standard
.info files. No image data is changed. Copied from Secret Weapons of the
Luftwaffe's `release/icons` (manifest/references.tsv), which has them from
Pokeri/Slicks.

- `drawer.info.b64`: WHDLoad Install Template / `Xxx Install.info`.
- `install.info.b64`: Rescue on Fractalus / whdload / `RoF Install/Install.info`.
- `game.inf.b64`: the same release's `RoF.inf`, packaged as `XWing.inf`.
- `readme.info.b64`: the same release's `ReadMe.info` (MultiView default tool).

The released reference archive is https://whdload.de/games/RescueOnFractalus.lha.
Installer copies the game icon to `XWing.info` and sets WHDLoad, Slave, PreLoad
and stack. Packaging changes only the Install icon's length-prefixed APPNAME
field. Default tool Installer, LOG=FALSE, PRETEND=FALSE, no SCRIPT.
