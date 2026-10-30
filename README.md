# Export Bodies for Fusion 360

Export every body in your Fusion 360 design as its own STL, 3MF or OBJ file, in one click.

![Export Bodies dialog](images/export-dialog.png)

## Features

- Select which bodies to export, or select all
- Export as STL, 3MF or OBJ
- Choose mesh quality
- Keep assembly position or change placement
- Apply a scale factor
- Add a filename prefix and suffix, with an optional document-name prefix
- Choose your output folder

## Install

1. Go to the [Releases page](../../releases/latest) and download `ExportBodies.zip`.
2. Unzip it. You should get a folder named `ExportBodies`.
3. In Fusion, open **Utilities > Add-Ins > Scripts and Add-Ins**.
4. Click the green **+** and select the `ExportBodies` folder.
5. Select **Export Bodies** and click **Run**. Tick **Run on Startup** to load it automatically.

> Don't use "Code > Download ZIP". GitHub renames that folder to `...-main`, and Fusion expects the folder name to match the add-in name.

## Use

1. Open your design in Fusion.
2. Run **Export Bodies**.
3. Tick the bodies you want, then pick the format, mesh quality and folder.
4. Click **Export**.

## Video walkthrough

[Watch on YouTube](YOUR_YOUTUBE_LINK)

Channel - https://www.youtube.com/@CodeandCraft3D

## Notes

- Tested on Fusion for Mac. Windows reports are welcome in [Issues](../../issues).
- Free for personal and commercial use under the MIT license.

## License

MIT. See [LICENSE](LICENSE).
