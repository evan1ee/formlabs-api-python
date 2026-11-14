## Install

Requirements: Windows 10 or 11 (64-bit), SOLIDWORKS 2025, and **PreForm 3.66.0.1146** with its server started.

1. Download `FormlabsSw-<version>-win64.zip` and unpack it. If Windows warns about the download, right-click the zip, choose *Properties*, tick *Unblock*, then unpack.
2. Close SOLIDWORKS.
3. Right-click `Install-FormlabsSw.ps1` and choose *Run with PowerShell*. It asks for administrator rights, copies the add-in to `C:\Program Files\Formlabs for SOLIDWORKS` and registers it.
4. Start PreForm and its server, open SOLIDWORKS, then tick *Tools > Add-Ins > Formlabs for SOLIDWORKS*.

Use: open a part or an assembly, open the Formlabs tab (purple butterfly), pick the material and layer, and click *Send active part to Formlabs*. See `USER_GUIDE.md` in the zip.

Uninstall: run `Uninstall-FormlabsSw.ps1` the same way. Your projects in `Documents\Formlabs Projects` are kept.

Verify the download: the SHA-256 of the zip is in `SHA256SUMS.txt`.

The zip contains an embedded Python runtime, the Formlabs SDK and the SOLIDWORKS API interop libraries, so nothing else needs to be installed.
