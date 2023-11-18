# BrightMarker Embedding Interface (BEI)

BEI is a Blender add-on that determines optimal locations/distributions on 3D models and embeds codes in them. Developed with Blender 3.4 Python API.

## Setup

1. **Install BEI.**
  
To install BEI, navigate to Edit -> Preferences -> Add-ons and click "Install...". Select BEI.py in your files, and the add-on will be installed. Make sure it's enabled by checking the box to the left of its name.  
  
2. **Enable LoopTools.**
  
BEI uses a Blender add-on called LoopTools. Navigate to Edit -> Preferences -> Add-ons, search "Mesh: LoopTools" (make sure that "Enabled Add-ons Only" is not checked or LoopTools won't show up), and check the box next to its name to enable it.
  
3. **Disable Auto Perspective.**
  
Navigate to Edit -> Preferences -> Navigation and make sure that Auto -> Perspective is not checked.

4. **Add ArUcos folder to Blender files**
  
Copy the "Arucos" folder to your working directory. To check your working directory, open Blender, navigate to the Scripting tab, and run the following code:
```python
import os
print(os.getcwd())
```
In Blender, click Window -> Toggle System Console. You should see a print statement with the directory in which you should place the "Arucos" folder.
In most cases, this will be your Blender program files, which are located at "C:\Program Files\Blender Foundation\Blender 3.4\" on Windows.

## Usage

Import your model (any 3D file type) and code (.svg, if you wish to embed your own codes) into Blender. Note that the code will import as a collection of curves. Ensure that Blender is in Object Mode, and select the model you would like to embed in. Note that setting the origin of your model to the center of its base can help with code alignment.

![image info](https://i.ibb.co/brKTGB7/Untitled.png)

Navigate to Object -> BrightMarker Embedding Interface.

**Steps**  
BEI has four steps to ensure your markers are embedded as you would like them to be.

1. **Marker Locations**

Use manually selected points: if you would like to use this setting, you must first enter Edit Mode, select individual faces on the model at which markers should be embedded, then re-enter Object Mode.
Use uniformly distributed points: this mode will find the best places on the model to uniformly distribute markers. You can choose to distribute on the whole object (with or without base or selected regions), or a selected region (select this region of faces on this model in Edit Mode, then re-enter Object Mode to run the BEI) based on a fixed total number of codes, or a fixed distance between codes.

2. **Marker Content**

Use fixed ArUco ID: this will embed a chosen ArUco ID for all of your markers.
Use sequential ArUco IDs: this will embed increasing ArUco IDs (starting from a chosen ID) for each marker.
Use custom marker: this will embed a custom code imported as a .svg into Blender for all of your markers.

3. **Marker Specifications**

Use suggested thicknesses for object color: this allows you to choose the color filament that your object will be printed with to automatatically determine the optimal marker and shell thicknesses.
Use custom values: this allows you to choose your own shell thickness (how deep in the model the marker is embedded) and marker thickness (how thick the marker is).
Side length: this sets the side length of all of the markers to be embedded (e.g. a side length of 10 means your markers will be 10 x 10).

4. **Marker Alignment**

Align marker bottom edge: this aligns the bottom edge of each marker to a desired plane with an optional angle offset.


Once you're satisfied with your settings, click **OK** and see the results! If you wish to export STLs, you must export the model with the air gaps as one STL, and just the codes as another STL.
