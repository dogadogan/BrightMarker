bl_info = {
    "name": "BrightMarker Embedding Interface (BEI)",
    "author": "Jamison O\'Keefe",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Object",
    "description": "Optimally embeds a code in an object",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}


import bpy
import bmesh
import mathutils
from mathutils import Matrix
import random
import math
from math import degrees,pi
import mesh_looptools as looptools
import copy
import numpy as np
from bpy.types import (
    AddonPreferences,
    Operator,
    Panel,
    PropertyGroup,
)
from bpy.props import (
    IntProperty,
    FloatProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
    FloatVectorProperty,
)


####### Smart Duplicate Operator #######

## Note: Edit > Preferences > Add Ons > looptools is required for this script's flatten functionality

class SmartDuplicate(Operator):
    bl_idname = "mesh.smart_duplicate"
    bl_label = "Smart Duplicate"
    bl_description = "Duplicates selection of faces and objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self,context):
        if context.mode == 'OBJECT':
            bpy.ops.object.duplicate()
        elif context.mode == 'EDIT_MESH':
            selectionMode = tuple(bpy.context.scene.tool_settings.mesh_select_mode)
            #print(selectionMode)
            #if Face is selected 
            ## JAMIE - selectionMode[2] condition started failing unexpectedly, hence I added 'or True'
            if selectionMode[2] or True:
                bpy.ops.mesh.duplicate()
                bpy.ops.mesh.separate(type='SELECTED')

                obj = context.object
                #bpy.ops.object.editmode_toggle()
                
                obj.select_set(False)
                context.view_layer.objects.active = context.selected_objects[-1]
    
        return {'FINISHED'}
    
bpy.utils.register_class(SmartDuplicate)

####### FUNCTIONS #######

def decimate(targetobj, targetfaces, numfaces):
    """
    Reduces an object with lots of faces to a specified number of faces.
    
    Input:
        targetobj (object to be decimated, must be selected as well)
        targefaces (int number of faces to reduce to)
        numfaces (int number of faces the object currently has)
    Return:
        None
    """
    ## Set to Object Mode 
    bpy.ops.object.mode_set(mode="OBJECT")
    ## Add Decimate modifier, name it "lowpoly" 
    targetobj.modifiers.new("lowpoly", "DECIMATE")
    ## Calculate Decimate ratio such that the object has targfaces faces after it's applied
    dratio = targetfaces/numfaces
    ## Set Decimate ratio
    targetobj.modifiers["lowpoly"].ratio = dratio
    ## Apply Decimate (note we need to be in Object Mode to apply a modifier) 
    bpy.ops.object.modifier_apply(modifier="lowpoly")

def get_bmesh(obj):
    """
    Gets the bmesh for an object.
    
    Input:
        obj (Blender object)
    Returns:
        bmesh of obj
    """
    bpy.ops.object.mode_set(mode="EDIT")
    
    return bmesh.from_edit_mesh(obj.data)

def get_flat_patches(bm, sharpnessval, ignorebottom, excludeselected = False):
    """
    Calculates a list, sorted by area, of approximately flat patches on the model.
    
    Input:
        obj (model to be analyzed)
        sharpnessval (float, lower value means patches must be flatter)
        ignorebottom (bool, True if the bottom should be ignored)
    Return:
        out (list of approx flat patches sorted from largest ot smallest)
    """
    bpy.ops.object.mode_set(mode="EDIT")
    print("exclude_selected", excludeselected)
    if excludeselected:
        to_exclude = [f for f in bm.faces if f.select]
        print(to_exclude)

    area = dict()
    ## Iterate over all faces in the mesh
    for face in bm.faces:
        exclusion_break = False
        ## If ignoring bottom and the face is within 15 degrees (0.26 radians) of the bottom, skip
        if ignorebottom and angle_between_norms(face.normal, (0, 0, -1)) < 0.26: continue
        ## Deselect all faces
        bpy.ops.mesh.select_all(action='DESELECT')
        ## Select the current face
        face.select = True
        ## Select all of the linked flat faces based on a sharpness value
        bpy.ops.mesh.faces_select_linked_flat(sharpness=sharpnessval)
        
        if excludeselected:
            for f in to_exclude:
                if f.select == True:
                    exclusion_break = True
                    break
        
        if not exclusion_break:
            ## Create list of selected faces
            group = [f for f in bm.faces if f.select]
            ## Find the total area of the group
            size = sum(f.calc_area() for f in group)
            ## Add starting face : (size, group) to dictionary
            if (size, group) not in list(area.values()):
                area[face] = (size,group)
    ## Create list of (size, group)s and sort by largest to smallest size
    out = list(area.values())
    out.sort(key=lambda y: y[0],reverse = True)
    ## Deselect all
    bpy.ops.mesh.select_all(action='DESELECT')    
    
    return out

def show_n_largest(out, n):
    """
    Selects the nth largest path of flat mesh.
    
    Input: 
        out (list of tuples)
        n (int) representing the nth largest patch
    Return:
        None
    """
    for face in out[n][1]:
        face.select = True

def remove_local_rotation(patch, override):
    """
    Zeros the local rotation of a patch
    
    Input: 
        patch (patch object, must be active)
    Return: 
        patch_rot (the local rotation the patch had when it was input)
    """
    bpy.ops.object.mode_set(mode="EDIT")
    ## Create custom orientation about patch
    or_name = "patchor"
    
    patchbm = get_bmesh(patch)
    
    for face in patchbm.faces:
        face.select = True
    ## Deselect one face so that orientation can be made for flat patch
    for face in patchbm.faces:
        face.select = False
        break
    
    bpy.ops.transform.create_orientation(override, name=or_name, overwrite=True)

    bpy.ops.object.mode_set(mode="OBJECT")
    ## Transform affect only origins
    bpy.context.scene.tool_settings.use_transform_data_origin = True
    ## Align to custom orientation
    bpy.ops.transform.transform(mode='ALIGN', orient_type=or_name)
    ## Save the rotation of the patch for later
    patch_rot = np.copy(patch.rotation_euler)
    ## Reset rotation
    patch.rotation_euler = (0, 0, 0)
    ## Revert to previous setting
    bpy.context.scene.tool_settings.use_transform_data_origin = False
    
    return patch_rot

def convert_to_array(patch, dimx, dimy, interval, startloc):
    """
    Converts a patch to a 2D Numpy array of 1s and 0s
    
    Input:
        patch (patch object to be converted)
        dimx (int width of array)
        dimy (int height of the array)
        interval (float distance between ray casts - this should be calculated based off dimx and dimy)
        startloc (tuple len 3 starting location for array - this should be -x +y corner of patch bounding box)
    Return:
        patcharray (2D Numpy array)
    """
    ## This will be our resulting array
    patcharray = np.array([])
    ## Iterate in a grid-like fashion over the area of the patch
    for y in range (dimy):
        for x in range (dimx):
            loc = (startloc[0] + x * interval, startloc[1] - y * interval, startloc[2])
            ## If the patch is present at that location, store a 1
            if patch.ray_cast(loc, (0, 0, -1))[0]:
                patcharray = np.append(patcharray, 1)
            ## If the patch is not present, store a 0
            else:
                patcharray = np.append(patcharray, 0)
    ## Reshape the array to be 2 dimensional
    patcharray = np.reshape(patcharray, (dimy, dimx))
    ## This line formats the array for lir
    patcharray = np.array(patcharray, "bool")
    #np.savetxt("binarized.txt", patcharray, fmt="%d")
    
    return patcharray

def create_mesh_from_verts(verts, name):
    """
    Returns an object containing a mesh created from specified vertices
    
    Input:
        verts (list of vertices)
        name (name of object)
    Return:
        optimal (newly created object)
    """
    ## Create the mesh
    mybm = bmesh.new()
    for vert in verts:
        ## Add our calculated vertices
        mybm.verts.new(vert)
    ## Create the faces
    mybm.faces.new(mybm.verts[:3])
    mybm.faces.new(mybm.verts[1:])
    mybm.normal_update()
    myme = bpy.data.meshes.new("")
    mybm.to_mesh(myme)
    ## Create optimal square object
    optimal = bpy.data.objects.new(name, myme)
    
    return optimal

def largest_interior_square(M):
    """
    Finds the largest square of 1s in an array of 1s and 0s
    
    Input:
        M (2D numpy array)
    Return:
        [(coordinates of bottom right of square), side length]
    """
    x, y = M.shape
    S = [[0 for _ in range(y)] for _ in range(x)] 
    max_s = 0
    coords = (0, 0)
    for i in range(1, x): 
        for j in range(1, y): 
            if M[i][j] == 1: 
                S[i][j] = min(S[i][j-1], S[i-1][j], S[i-1][j-1]) + 1
                if S[i][j] > max_s:
                    max_s = S[i][j]
                    coords = (j, i)                   
    
    return [coords, max_s]

def angle_between_norms(v1, v2):
    """
    Finds the angle between two 3-dimensional normal vectors in degrees.
    
    Input:
        v1 (tuple of length 3)
        v2 (tuple of length 3)
    Return:
        ang (float)
    """
    dotprod = np.dot(v1, v2)
    ## Get rid of tiny decimals that don't fall in math.acos() bounds
    dotprod = min(dotprod, 1)
    dotprod = max(dotprod, -1)
    ## We know the magnitude of the norms will be 1
    ang = math.acos(dotprod)
        
    return ang

def find_target_collection(obj, col):
    """
    Finds and returns the LayerCollection that is the immediate parent of the target obj.
    
    Input:
        obj (target object)
        col (LayerCollection, defaults to the top of the hierarchy)
        
    Returns:
        LayerCollection containing the target obj
    """
    col_objs = col.collection.objects
    ## If the object is in the collection, return it
    for i in range(len(col_objs)):
        if col_objs[i] == obj:
            return col
    ## If this collection doesn't contain obj, recurse
    for child_collection in col.children:
        res = find_target_collection(obj, child_collection)
        if res != None:
            return res
    ## If this collection tree doesn't contain obj, return None
    return None

def distance_between_vectors(v1, v2):
    """
    Calculate the distance between two Vectors.
    """
    return ((v1.x - v2.x)**2 + (v1.y - v2.y)**2 + (v1.z - v2.z)**2)**0.5

def indices_to_coords(startloc, interval, row, col):
    """
    Calculate the real coords from a start location, interval, and index.
    """
    res = (startloc[0] + col*interval, startloc[1] - row*interval, 0)
    return res


class OBJECT_OT_optimalembed(Operator):
    bl_label = "BrightMarker Embedding Interface"
    bl_idname = "object.optimalembed"
    bl_description = "Optimally embeds a code in an object"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {'REGISTER', 'UNDO'}
    
    maxfaces: bpy.props.IntProperty(
        name = "Max faces",
        default = 1250,
        min = 750,
        max = 4000,
        description = "Reduces the object's geometry to this number of faces if it is more detailed",
    )
    
    sharpness: bpy.props.FloatProperty(
        name = "Sharpness",
        default = 0.1,
        min = 0,
        max = 2,
        description = "The angle (radians) between two connected faces at or below which they are considered flat",
    )
    
    accuracy: bpy.props.FloatProperty(
        name = "Accuracy",
        default = 1,
        min = 0,
        max = 2,
        description = "Scales the dimensions, and therefore accuracy, of array creation. Between 0.75 and 1 will suffice for nearly all purposes",
    )
    
    codes: bpy.props.IntProperty(
        name = "Number of codes",
        default = 1,
        min = 1,
        max = 10,
        description = "The number of places the code will be embedded in the object (or number of optimal locations displayed if \"Embedding Code?\" is unchecked))",
    )
    codename: bpy.props.StringProperty(
        name = "File name of code",
        default = "my-qr-code.svg",
        description = "The name of your imported code collection, usually imported as the file name. e.g. valid input woukd be \"qr-code-download.svg\"",
    )
    
    offset: bpy.props.FloatProperty(
        name = "Shell thickness",
        default = 0.1,
        min = 0,
        max = 9999,
        description = "The distance (in Blender units) that the code will be embedded under the object's surface",
    )
    
    thickness: bpy.props.FloatProperty(
        name = "Marker thickness",
        default = 0.1,
        min = 0,
        max = 100,
        description = "The desired thickness (in Blender units) of the embedded code",
    )
    """
    usingemb: bpy.props.BoolProperty(
        name = "Use automated optimal locations",
        default = False,
        description = "Check if you are using this mode",
    )
    """
    usingman: bpy.props.BoolProperty(
        name = "Use manually selected points",
        default = False,
        description = "Check if you are using this mode",
    )
    sidelength: bpy.props.FloatProperty(
        name = "Side length",
        default = 100,
        min = 0,
        max = 1000,
        description = "The side length of embedded markers",
    )
    aligncode: bpy.props.BoolProperty(
        name = "Align marker bottom edge",
        default = False,
        description = "Check if you want to align your codes to a set local Z rotation",
    )
    plane: bpy.props.EnumProperty(
        name = "Plane",
        description = "Select the plane you would like to align your codes to",
        items = [
            ('opxy', "XY", "XY Plane"),
            ('opyz', "YZ", "YZ Plane"),
            ('opxz', "XZ", "XZ Plane"),
        ]
    )
    alignangle: bpy.props.FloatProperty(
        name = "Angle (deg)",
        default = 0,
        min = 0,
        max = 360,
        description = "This sets the local Z rotation for all codes",
    )
    sequential: bpy.props.BoolProperty(
        name = "Use sequential ArUco IDs",
        default = False,
        description = "Embed ArUcos with increasing IDs (0, 1, 2, 3, etc.)",
    )
    usinggeometric: bpy.props.BoolProperty(
        name = "Use uniformly distributed points",
        default = False,
        description = "Check if you are using this mode",
    )
    """
    remscale: bpy.props.FloatProperty(
        name = "Marker Density",
        default = 0.99,
        min = 0.5,
        max = 0.99,
        description = "This sets the local Z rotation for all codes",
    )
    """
    uniformparam: bpy.props.EnumProperty(
        name = "On",
        description = "Select the surface(s) into which you would like to embed",
        items = [
            ('op1', "Whole Object", "Uniformly distribute codes over the whole object"),
            ('op3', "Whole Object Except Base", "Uniformly distribute codes over the whole object"),
            ('op4', "Whole Object Except Selected Region(s)", "Uniformly distribute codes over the whole object, excluding regions which include the selected face(s)"),
            ('op2', "Selected Region", "Uniformly distribute codes over the selected region"),
        ]
    )
    fixedaruco: bpy.props.BoolProperty(
        name = "Use fixed ArUco ID",
        default = False,
        description = "Embed a certain ArUco",
    )
    fixedarucoid: bpy.props.IntProperty(
        name = "ID",
        default = 0,
        min = 0,
        max = 50,
        description = "The ArUco ID to be embedded",
    )
    startingat: bpy.props.IntProperty(
        name = "Starting at ID",
        default = 0,
        min = 0,
        max = 50,
        description = "The ArUco ID start of the sequence",
    )
    custom: bpy.props.BoolProperty(
        name = "Use custom marker",
        default = False,
        description = "Embed a custom (imported) code",
    )
    fixednum: bpy.props.BoolProperty(
        name = "Fixed # of Markers",
        default = False,
        description = "Embed a fixed number of markers",
    )
    intermarker: bpy.props.BoolProperty(
        name = "Fixed inter-marker distance",
        default = False,
        description = "Embed a number of markers determined by the specified distance between them and the space available on the model",
    )
    uniformdist: bpy.props.FloatProperty(
        name = "Distance between markers",
        default = 1,
        min = 0,
        max = 1000,
        description = "This specifies how far apart the codes will be",
    )
    suggestoffset: bpy.props.BoolProperty(
        name = "Use suggested thicknesses for object color",
        default = False,
        description = "Use the suggested depth for your print filament",
    )
    customoffset: bpy.props.BoolProperty(
        name = "Use custom values",
        default = False,
        description = "Use a custom depth",
    )
    chosencolor: bpy.props.EnumProperty(
        name = "Color",
        description = "Select the color of your filament",
        items = [
            ('red', "Red", "Use this color's suggested marker depth"),
            ('green', "Green", "Use this color's suggested marker depth"),
            ('blue', "Blue", "Use this color's suggested marker depth"),
            ('magenta', "Magenta", "Use this color's suggested marker depth"),
            ('black', "Black", "Use this color's suggested marker depth"),
            ('white', "White", "Use this color's suggested marker depth"),
            ('irtrans', "IR Transparent", "Use this color's suggested marker depth"),
        ]
    )
    fullarucopath: bpy.props.BoolProperty(
        name = "Use full path (Mac)",
        default = False,
        description = "Check this box if you would like to input the full path to your Arucos folder rather than using the working directory (NECESSARY FOR MAC USERS)",
    )
    pathcontent: bpy.props.StringProperty(
        name = "Path to \'Arucos\' folder",
        default = "",
        description = "Input the path that results when you drag and drop your Arucos folder into the terminal",
    )


    """
    @classmethod
    def poll(cls, context):
        return context.object.select_get() and context.object.type == 'MESH'
    """
    
    def draw(self, context):
        
        ob = bpy.context.object
        
        layout = self.layout
        """
        # Give the user info on the size of their model in Blender units
        sizex = max(vert.co.x for vert in ob.data.vertices) - min(vert.co.x for vert in ob.data.vertices)
        sizey = max(vert.co.y for vert in ob.data.vertices) - min(vert.co.y for vert in ob.data.vertices)
        sizez = max(vert.co.z for vert in ob.data.vertices) - min(vert.co.z for vert in ob.data.vertices)
        layout.label(text = f"Dimensions of your model's bounding box:")
        layout.label(text = f"{np.format_float_scientific(sizex, 1)} x {np.format_float_scientific(sizey, 1)} x {np.format_float_scientific(sizez, 1)} (X x Y x Z)")
        """

        # 1. marker locations
        
        box = layout.box()
        
        box.label(text="1. Marker Locations")
        
        row = box.row()
        row.prop(self, "usingman")
        row.enabled = not self.usinggeometric
        
        row = box.row()
        row.prop(self, "usinggeometric")
        row.enabled = not self.usingman
        
        if self.usinggeometric:
            row = box.row()
            row.prop(self, "uniformparam")
              
            row = box.row()
            row.label(text="Based on:")
                
            if not self.intermarker:
                row = box.row()
                row.prop(self, "fixednum")
                
            if self.fixednum:
                row = box.row()
                row.prop(self, "codes")
                
            if not self.fixednum:
                row = box.row()
                row.prop(self, "intermarker")
                
            if self.intermarker:
                row = box.row()
                row.prop(self, "uniformdist")
                
            
                
        layout.row().separator()
                
        
        # 2. marker pattern
        
        box = layout.box()
        
        box.label(text="2. Marker Content")
        
        if not self.sequential and not self.custom:
            row = box.row()
            row.prop(self, "fixedaruco")
        
        if self.fixedaruco:
            row = box.row()
            row.prop(self, "fixedarucoid")
        
        if not self.fixedaruco and not self.custom:
            row = box.row()
            row.prop(self, "sequential")
        
        if self.sequential:
            row = box.row()
            row.prop(self, "startingat")

        if self.fixedaruco or self.sequential:
            row = box.row()
            row.prop(self, "fullarucopath")

            if self.fullarucopath:
                row = box.row()
                row.prop(self, "pathcontent")
        
        if not self.fixedaruco and not self.sequential:
            row = box.row()
            row.prop(self, "custom")
        
        if self.custom:
            row = box.row()
            row.prop(self, "codename")
        
        layout.row().separator()
        
        
        # 3. marker specs
        
        box = layout.box()
        
        box.label(text="3. Marker Specifications")
        
        row = box.row()
        row.label(text = "Marker and shell thickness:")
        
        if not self.customoffset:
            row = box.row()
            row.prop(self, "suggestoffset")
        
        if self.suggestoffset:
            row = box.row()
            row.prop(self, "chosencolor")
        
        if not self.suggestoffset:
            row = box.row()
            row.prop(self, "customoffset")
        
        if self.customoffset:
            row = box.row()
            row.prop(self, "thickness")
            
            row = box.row()
            row.prop(self, "offset")
        
        row = box.row()
        row.label(text = "Marker size:")
        
        row = box.row(align=True)
        row.prop(self, "sidelength")
        
        layout.row().separator()
        
        # 4. marker alignment
        
        box = layout.box()
        
        box.label(text="4. Marker Alignment")
            
        row = box.row()
        row.prop(self, "aligncode")
        if self.aligncode:
            row = box.row()
            row.prop(self, "plane")
            row.prop(self, "alignangle")    
        
        layout.row().separator()
        

    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        ####### ACTIONS BEGIN HERE #######
        
        self.path_to_arucos = "Arucos/" if not self.fullarucopath else self.pathcontent

        ## Color: (thickness, offset)
        colordict = {
        'red': (1.2, 0.9), 
        'green': (1.2, 0.6), 
        'blue': (1.2, 0.6), 
        'magenta': (1.2, 0.8), 
        'black': (1.2, 0.8), 
        'white': (1.2, 0.6),
        'irtrans': (1.2, 1.2),
        }

        ## We need a text editor window to create an override for remove_local_rotation
        area = bpy.context.area
        old_type = area.type
        area.type = "TEXT_EDITOR"
        ## override ensures that create_orientation will run (even with the wrong context)
        for area in bpy.context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        txtoverride = {'area': area, 'region': region}
        self.txtoverride = txtoverride
        ## Revert back to previous context
        area.type = old_type


        bpy.ops.object.mode_set(mode="OBJECT")
        ## Store an unadultered copy of the model
        ORIG_OBJ = bpy.context.object
        ## Make sure the direct parent collcetion of the desired model is active
        bpy.context.view_layer.active_layer_collection = find_target_collection(ORIG_OBJ, bpy.context.view_layer.layer_collection)
        ## List to store the approx flat patches
        patches = []
        
        Whole_Object = self.uniformparam in ('op1', 'op3', 'op4')
        Exclude_Selected = self.uniformparam == 'op4'
        if self.usinggeometric and Whole_Object:

            bpy.ops.object.duplicate()
            objcopy = bpy.context.object
            ## Select obj
            bpy.ops.object.select_all(action='DESELECT')
            objcopy.select_set(state = True)
            bpy.context.view_layer.objects.active = objcopy
            bm = get_bmesh(objcopy)
        
            ## Check if number of faces exceeds maximum 
            numfaces = len(bm.faces)
            if numfaces > self.maxfaces:
                decimate(objcopy, self.maxfaces, numfaces)
        
            ## Select our copy
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action='DESELECT')
            objcopy.select_set(state = True)
            bpy.context.view_layer.objects.active = objcopy
            
            ## Get approximately flat patches
            bm = get_bmesh(objcopy)
            out = get_flat_patches(bm, self.sharpness, self.uniformparam == "op3", Exclude_Selected)
            
            if self.fixednum:
                number_of_patches = self.codes
            if self.intermarker:
                number_of_patches = len(out)
                for ind, (size, group) in enumerate(out):
                    if size < 1.5 * self.sidelength**2:
                        number_of_patches = ind
                        break
            
            
            for iter in range(number_of_patches):
                
                if Whole_Object:
                    bpy.ops.mesh.select_all(action='DESELECT')
                    ## Select approximately flat patch
                    show_n_largest(out, iter)

                ####### CREATE A FLATTENED COPY OF THE APPROXIMATELY FLAT AREA ON THE MODEL #######

                ## Duplicate the patch
                bpy.ops.mesh.smart_duplicate()
                
                copy = bpy.context.object 
                copybm = get_bmesh(copy)
                ## Select the faces in the copy
                for face in copybm.faces:
                    face.select = True
                ## Flatten the copy
                looptools.bpy.ops.mesh.looptools_flatten()
                
                ## Assign flat patch object
                patch = bpy.context.object
                patch.name = f"Patch {iter+1}"
                patches.append(patch)
            
            ## Delete the decimated copy of the original object
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = objcopy
            objcopy.select_set(state = True)
            bpy.ops.object.delete()
        
        
        elif self.usinggeometric and not Whole_Object: ## Uniform selected region
            ## Duplicate the patch
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.smart_duplicate()
            copy = bpy.context.object 
            copybm = get_bmesh(copy)
            ## Select the faces in the copy
            for face in copybm.faces:
                face.select = True
            ## Flatten the copy
            looptools.bpy.ops.mesh.looptools_flatten()
            ## Assign flat patch object
            patch = bpy.context.object
            patch.name = f"Selected Region Patch"
            patches.append(patch)
        
        
        else: # If user chose locations (faces) manually
            #print("MANUAL")
            ## Create a list of the faces selected by the user
            userfaces = []
            origbm = get_bmesh(ORIG_OBJ)
            for face in origbm.faces:
                if face.select: userfaces.append(face)
            
            iter = 0
            for origface in userfaces:
                ## Deselect all faces
                bpy.ops.mesh.select_all(action='DESELECT')
                ## Get position of origface
                pos_0 = origface.calc_center_bounds()
                ## Get current face normal
                norm_0 = origface.normal
                ## Select the current face
                origface.select = True
                ## Select all of the linked flat faces based on a sharpness value
                bpy.ops.mesh.faces_select_linked_flat(sharpness=self.sharpness)
                
                for f in origbm.faces:
                    if f.select:
                        if abs(angle_between_norms(norm_0, f.normal)) > (1):
                            f.select = False
                        else:
                            pos_f = f.calc_center_bounds()
                            dist = ((pos_0[0] - pos_f[0])**2 + (pos_0[1] - pos_f[1])**2 + (pos_0[2] - pos_f[2])**2)**0.5
                            if dist > self.sidelength:
                                f.select = False
                
                patchgroupcopy = [f for f in origbm.faces if f.select]
                patchgroup = list(np.copy(patchgroupcopy))
                
                ## Make sure there aren't multiple, disconnected patches
                for patchface in patchgroupcopy:
                    
                    bpy.ops.mesh.select_all(action='DESELECT')
                    patchface.select = True
                    origface.select = True
                    
                    ## Select faces in path between
                    bpy.ops.mesh.shortest_path_select(edge_mode='SELECT')
                    
                    for f in origbm.faces:
                        if f.select and f not in patchgroupcopy:
                        ## If a face in the path is not in the patchgroup, then there are disconnected patches
                            patchgroup.remove(patchface)
                            break
                
                bpy.ops.mesh.select_all(action='DESELECT')
                for f in patchgroup:
                    f.select = True
                
                
                ## Duplicate the patch
                bpy.ops.mesh.smart_duplicate()
                copy = bpy.context.object 
                copybm = get_bmesh(copy)
                ## Select the faces in the copy
                for face in copybm.faces:
                    face.select = True
                ## Flatten the copy
                looptools.bpy.ops.mesh.looptools_flatten()
                ## Assign flat patch object
                patch = bpy.context.object
                patch.name = f"Patch {iter+1}"
                patches.append(patch)
                iter += 1

        ## For sequential embedding with uniform mode
        self.uniform_aruco_iter = 0
        self.uniform_aruco_iter_del = 0
        ## iter is just a counter for the following for loop. I know it has the same name as the iterable in the previous loops. Idc.
        iter = 0
        for patch in patches:
            
            ####### RESET POSITION AND ROTATION OF PATCH SO THAT IT LAYS FLAT ON THE XY PLANE AT THE ORIGIN #######

            bpy.context.view_layer.objects.active = patch
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action='DESELECT')
            patch.select_set(state = True)
            bpy.context.view_layer.objects.active = patch
            
            ## Set the object origin to the center of its geometry
            #bpy.ops.object.origin_set(type = "ORIGIN_GEOMETRY")
            bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS')
            ## Save the location of the patch for later
            patch_loc = np.copy(patch.location)
            ## Set location to (0, 0, 0) (center the flat copy patch)
            patch.location = (0, 0, 0)
            ## Save local rotation for later
            patch_rot = remove_local_rotation(patch, self.txtoverride)

            ####### CONVERT PATCH TO ARRAY OF 1s AND 0s #######

            ## Get the x and y bounds of the patch
            min_x = min([vert.co.x for vert in patch.data.vertices])
            max_x = max([vert.co.x for vert in patch.data.vertices])
            min_y = min([vert.co.y for vert in patch.data.vertices])
            max_y = max([vert.co.y for vert in patch.data.vertices])
            ## Choose the detail (dimensions) of the array in the x direction
            dimx = int(300 * self.accuracy) + 1
            ## Calculate dimension in the y direction to ensure the interval is consistent
            dimy = int(dimx * ((max_y - min_y) / (max_x - min_x))) + 1
            ## Calculate the interval
            interval = (max_x - min_x) / dimx
            ## Starting location for ray casts
            startloc = (min_x, max_y, 1)

            patcharray = convert_to_array(patch, dimx, dimy, interval, startloc)
            
            if self.usingman or self.fixednum:
                ####### GET THE LARGEST INTERIOR RECTANGLE IN THE PATCH #######

                ## mylis stores the (i, j) coordinates of the bottom right of the square, followed by the side length
                mylis = largest_interior_square(patcharray)
                ## Bottom right x and bottom right y
                brx, bry = mylis[0]
                ## Side length
                s = mylis[1]
                ## Now we need ot get the vertices of the rectangle so we can create it as a new object
                topleft = (startloc[0] + (brx - s) * interval, startloc[1] - (bry - s) * interval, 0)
                topright = (startloc[0] + brx * interval, startloc[1] - (bry - s) * interval, 0)
                bottomleft = (startloc[0] + (brx - s) * interval, startloc[1] - bry * interval, 0)
                bottomright = (startloc[0] + brx * interval, startloc[1] - bry * interval, 0)
                verts = [topleft, topright, bottomleft, bottomright]

                optimal = create_mesh_from_verts(verts, "OptimalSquare")
                bpy.context.collection.objects.link(optimal)
                ## Move the optimal rectangle to its original location on the model
                optimal.location = patch_loc
                optimal.rotation_euler = patch_rot
                           
                ## Delete the patch as we no longer need it
                bpy.context.view_layer.objects.active = patch
                patch.select_set(state = True)
                bpy.ops.object.delete()
                
                ####### CONFIGURE THE QR CODE #######
                
                ## Get width of optimal square
                optimal_w = max([vert.co.x for vert in optimal.data.vertices]) - min([vert.co.x for vert in optimal.data.vertices])
                ## Save this value (for presenting the codes off to the side)
                if iter == 0:
                    self.optimal_w = optimal_w
                
                ## If using max/min widths...
                #if optimal_w > self.sidelength:
                multiplier = self.sidelength / optimal_w
                optimal.scale.x *= multiplier
                optimal.scale.y *= multiplier
                bpy.context.view_layer.objects.active = optimal
                optimal.select_set(state = True)
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                optimal_w = max([vert.co.x for vert in optimal.data.vertices]) - min([vert.co.x for vert in optimal.data.vertices])
                """
                if optimal_w < self.sidelength:
                    bpy.context.view_layer.objects.active = optimal
                    optimal.select_set(state = True)
                    bpy.ops.object.delete()
                    continue
                """
            
            if self.usinggeometric and self.intermarker:
                
                ####### GET UNIFORM POINTS IN THE PATCH #######
                
                interdist = self.uniformdist if self.intermarker else self.sidelength / 15
                    
                units_between = int((self.sidelength + interdist) / interval)
                #print (units_between)
                
                numrows = int(len(patcharray) / (self.sidelength / interval))
                
                #print (f"total rows: {len(patcharray)}")
                
                points = []
                
                edge_gap = int((self.sidelength / 1.8) / interval)
                for i in range (numrows):
                    row = edge_gap + int(units_between * i)
                    
                    if row < len(patcharray):
                        rowlist = list(patcharray[row])
                        
                        start = rowlist.index(1)
                        end = len(rowlist) - list(reversed(rowlist)).index(1)
                        
                        cols = []
                        col = start + edge_gap
                        while True:
                            if col > (end - edge_gap): break
                            if rowlist[col] == 1:
                                cols.append(col)
                            else:
                                col += rowlist[col:].index(1) + edge_gap
                                if col > (end - edge_gap): break
                                cols.append(col)
                            col += units_between
                        if cols:
                            centershift = int(((end - edge_gap) - cols[len(cols) - 1])/2)
                            for coln in cols:
                                coln += centershift
                                if patcharray[row - int(edge_gap / 2)][coln] == 1 and patcharray[row + int(edge_gap / 3)][coln] == 1:
                                    points.append((row, coln))
                if points:
                    if points[0][1] != points[len(points) - 1][1]:
                        vertshift = int(((len(patcharray) - points[len(points) - 1][1]) - points[0][1])/2)
                        for rw, cn in points:
                            rw += vertshift
            
            
        
            if self.custom or self.fixedaruco: ## If the user is embedding their own code
                if iter == 0:
                    if self.fixedaruco:
                        bpy.ops.import_curve.svg(filepath=f"{self.path_to_arucos}{self.fixedarucoid}.svg")
                        codecol = bpy.data.collections.get(f"{self.fixedarucoid}.svg")
                    else:
                        codecol = bpy.data.collections.get(self.codename)
                    ## Join the curves in the code SVG only if this is the first iteration

                    ## Convert all of the curves to meshes
                    for curveobj in codecol.all_objects:
                        curveobj.select_set(state = True)
                        bpy.context.view_layer.objects.active = curveobj
                        bpy.ops.object.convert(target='MESH')
                    bpy.context.view_layer.objects.active = codecol.all_objects[0]
                    with bpy.context.temp_override(active_object=bpy.context.active_object, selected_editable_objects=codecol.all_objects):
                        bpy.ops.object.join()
                    ## Get the single, joined object
                    codeobj = codecol.all_objects[0]
                    
                    ## Remove doubles from codemesh
                    bpy.context.view_layer.objects.active = codeobj
                    codeobj.select_set(state = True)
                    bpy.ops.object.mode_set(mode="EDIT")
                    for face in get_bmesh(codeobj).faces:
                        face.select = True
                    bpy.ops.mesh.remove_doubles()   
                    bpy.ops.object.mode_set(mode="OBJECT") 
                        
                    ## Set origin to the center of the code
                    bpy.context.scene.cursor.location = (max(vert.co.x for vert in codeobj.data.vertices)/2, max(vert.co.y for vert in codeobj.data.vertices)/2, 0)
                    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                    
                    ## Duplicate and store the code mesh
                    bpy.ops.object.select_all(action='DESELECT')
                    bpy.context.view_layer.objects.active = codeobj
                    codeobj.select_set(state = True)
                    bpy.ops.object.duplicate()
                    self.codemesh = bpy.context.object
                    self.codemesh.name = "CodeMesh"
                        
                        
                ## Else, we already have a stored codemesh. We just need to copy it and work on the copy.
                else:
                    bpy.context.view_layer.objects.active = self.codemesh
                    self.codemesh.select_set(state = True)
                    bpy.ops.object.duplicate()
                    codeobj = bpy.context.object
            
            elif self.sequential and (self.usingman or self.fixednum): ## If the user is embedding sequential arucos
                bpy.ops.import_curve.svg(filepath=f"{self.path_to_arucos}{iter + self.startingat}.svg")
                codecol = bpy.data.collections.get(f"{iter + self.startingat}.svg")
                
                ## Convert all of the curves to meshes
                for curveobj in codecol.all_objects:
                    curveobj.select_set(state = True)
                    bpy.context.view_layer.objects.active = curveobj
                    bpy.ops.object.convert(target='MESH')
                bpy.context.view_layer.objects.active = codecol.all_objects[0]
                with bpy.context.temp_override(active_object=bpy.context.active_object, selected_editable_objects=codecol.all_objects):
                    bpy.ops.object.join()
                ## Get the single, joined object
                codeobj = codecol.all_objects[0]
                
                ## Remove doubles from code mesh
                bpy.ops.object.mode_set(mode="EDIT")
                for face in get_bmesh(codeobj).faces:
                    face.select = True
                bpy.ops.mesh.remove_doubles()   
                bpy.ops.object.mode_set(mode="OBJECT")
                    
                ## Set origin to the center of the code
                bpy.context.scene.cursor.location = (max(vert.co.x for vert in codeobj.data.vertices)/2, max(vert.co.y for vert in codeobj.data.vertices)/2, 0)
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
            else: pass
                
                
                
            if self.usinggeometric and self.intermarker:
                codes_to_embed = []
                for pt in points:
                    if self.sequential: ## create the sequential codes within this loop
                        bpy.ops.object.mode_set(mode="OBJECT")
                        bpy.ops.import_curve.svg(filepath=f"{self.path_to_arucos}{self.uniform_aruco_iter + self.startingat}.svg")
                        codecol = bpy.data.collections.get(f"{self.uniform_aruco_iter + self.startingat}.svg")
                        ## Convert all of the curves to meshes
                        for curveobj in codecol.all_objects:
                            curveobj.select_set(state = True)
                            bpy.context.view_layer.objects.active = curveobj
                            bpy.ops.object.convert(target='MESH')
                        bpy.context.view_layer.objects.active = codecol.all_objects[0]
                        with bpy.context.temp_override(active_object=bpy.context.active_object, selected_editable_objects=codecol.all_objects):
                            bpy.ops.object.join()
                        ## Get the single, joined object
                        codeobj = codecol.all_objects[0]
                
                        ## Remove doubles from code mesh
                        bpy.ops.object.mode_set(mode="EDIT")
                        for face in get_bmesh(codeobj).faces:
                            face.select = True
                        bpy.ops.mesh.remove_doubles()   
                        bpy.ops.object.mode_set(mode="OBJECT")
                            
                        ## Set origin to the center of the code
                        bpy.context.scene.cursor.location = (max(vert.co.x for vert in codeobj.data.vertices)/2, max(vert.co.y for vert in codeobj.data.vertices)/2, 0)
                        bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                            
                    
                    bpy.context.view_layer.objects.active = codeobj
                    codeobj.select_set(state = True)
                    bpy.ops.object.duplicate()
                    codecopy = bpy.context.object
                    codecopy.location = indices_to_coords(startloc, interval, pt[0], pt[1])
                    codecopy.scale.x *= self.sidelength / codecopy.dimensions.x
                    codecopy.scale.y *= self.sidelength / codecopy.dimensions.y
                    
                    bpy.context.scene.cursor.location = (0, 0, 0)
                    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                    codecopy.location = patch_loc
                    codecopy.rotation_euler = patch_rot

                    bpy.ops.object.mode_set(mode="OBJECT")
                    codes_to_embed.append(codecopy)
                    self.uniform_aruco_iter += 1
                
                
            if self.usingman or self.fixednum:
                ## Get width of code
                code_w = max([vert.co.x for vert in codeobj.data.vertices]) - min([vert.co.x for vert in codeobj.data.vertices])
                ## Scale code to the same size as the optimal square
                multiplier = optimal_w / code_w
                codeobj.scale.x *= multiplier
                codeobj.scale.y *= multiplier
                ## Move the code to the correct location on the model
                codeobj.rotation_euler = optimal.rotation_euler#patch_rot
                ## Move to code to the location of the optimal square
                bpy.ops.object.select_all(action='DESELECT')
                optimal.select_set(state = True)
                bpy.context.view_layer.objects.active = optimal
                bpy.ops.object.origin_set(type = "ORIGIN_GEOMETRY")
                codeobj.location = optimal.location

            
            ####### KNIFE PROJECTION #######
            
            ## bpy.ops.mesh.knife_project() needs view3d context and an editmesh
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    override = {'area': area}
                    space = area.spaces.active
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            override = {'area': area, 'region': region}
                    break
            
            if space.region_3d.view_perspective == "PERSP":
                bpy.ops.view3d.view_persportho(override)
            
            
            
            
            if self.usinggeometric and self.intermarker:
                num_embeds = len(codes_to_embed)
            else: num_embeds = 1
            
            for _ in range(num_embeds):
            
                ## Now, knife project the code
                proj_subject = codes_to_embed[_] if self.usinggeometric and self.intermarker else codeobj
                
                if self.aligncode:
                    bpy.ops.object.select_all(action='DESELECT')
                    bpy.context.view_layer.objects.active = proj_subject
                    proj_subject.select_set(state = True)
                    
                    verts = get_bmesh(proj_subject).verts
                    btmleft = max(verts, key = lambda vert : -vert.co.x - vert.co.y)
                    btmright = max(verts, key = lambda vert : vert.co.x - vert.co.y)
                    
                    mat = proj_subject.matrix_world
                    if self.plane == "opxy":
                        plane_norm = (0, 0, 1)
                    if self.plane == "opyz":
                        plane_norm = (1, 0, 0)
                    if self.plane == "opxz":
                        plane_norm = (0, 1, 0)
                    
                    vec_1 = (
                    (mat @ btmleft.co).x - (mat @ btmright.co).x, 
                    (mat @ btmleft.co).y - (mat @ btmright.co).y, 
                    (mat @ btmleft.co).z - (mat @ btmright.co).z
                    )
                    mag = (vec_1[0]**2 + vec_1[1]**2 + vec_1[2]**2)**0.5
                    vec_1_norm = (vec_1[0] / mag, vec_1[1] / mag, vec_1[2] / mag)
                    
                    ## Get its current local z rotation
                    ang = math.asin(np.dot(vec_1_norm, plane_norm))
                    
                    ## Set origin to the center of the code
                    bpy.context.scene.cursor.location = (
                    (max((mat @ vert.co).x for vert in proj_subject.data.vertices) + min((mat @ vert.co).x for vert in proj_subject.data.vertices))/2, 
                    (max((mat @ vert.co).y for vert in proj_subject.data.vertices) + min((mat @ vert.co).y for vert in proj_subject.data.vertices))/2,
                    (max((mat @ vert.co).z for vert in proj_subject.data.vertices) + min((mat @ vert.co).z for vert in proj_subject.data.vertices))/2,
                    )
                    bpy.ops.object.mode_set(mode="OBJECT")
                    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')

                    if self.plane != "opxz":
                        corrected_ang = 3.1415926 - abs(ang)
                        if ang < 0:
                            corrected_ang *= -1
                    else:
                        corrected_ang = ang
                    ## Rotate (subtract current rotation, add the user's desired rotation)
                    bpy.ops.transform.rotate(value=corrected_ang + math.radians(self.alignangle), orient_axis='Z', orient_type='LOCAL', orient_matrix_type='LOCAL', constraint_axis=(False, False, True), mirror=False, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False, snap=False, snap_elements={'INCREMENT'}, use_snap_project=False, snap_target='CLOSEST', use_snap_self=True, use_snap_edit=True, use_snap_nonedit=True, use_snap_selectable=False, release_confirm=True) 

                ## Create another copy of the original model to project onto
                bpy.ops.object.select_all(action='DESELECT')
                bpy.context.view_layer.objects.active = ORIG_OBJ
                ORIG_OBJ.select_set(state = True)
                bpy.ops.object.duplicate()
                obj2 = bpy.context.object
                obj2.name = "CopyOriginal2"
                
                ## Remove doubles from object copy
                ORIG_OBJ.select_set(state = False)
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.remove_doubles() 
                bpy.ops.object.mode_set(mode="OBJECT")
                
                bpy.ops.object.select_all(action='DESELECT')
                ## Select the subject
                proj_subject.select_set(state = True)
                bpy.context.view_layer.objects.active = proj_subject
                ## Remove double vertices
                bpy.ops.object.mode_set(mode="EDIT")
                for face in get_bmesh(proj_subject).faces:
                    face.select = True
                bpy.ops.mesh.remove_doubles()

                bpy.ops.object.mode_set(mode="OBJECT")
                ## Align view to face the mesh being projected
                bpy.ops.view3d.view_axis(override, type='TOP', align_active=True)
                ## Configure active and selected objects
                bpy.ops.object.select_all(action='DESELECT')
                obj2.select_set(state = True)
                bpy.context.view_layer.objects.active = obj2
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action='DESELECT')

                proj_subject.select_set(state = True)
                ## redraw_timer updates the 3D view so that we are facing the front of the proj_subject
                ## This is important to knife_project, which projects in the direction of the 3d view
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
                ## Project onto the model 
                bpy.ops.mesh.knife_project(override)
                ## Duplicate the projection as its own mesh in its own object
                bpy.ops.mesh.smart_duplicate()
                ## Store the projected code as "projectioncode"
                for tmpobj in bpy.context.selected_objects:
                    if tmpobj != proj_subject:
                        projectioncode = tmpobj
                projectioncode.name = f"Code Piece {iter + 1}"
                
                ## Remove double vertices
                for face in get_bmesh(projectioncode).faces:
                    face.select = True
                bpy.ops.mesh.remove_doubles()
                #bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
                ## Deselect projection
                projectioncode.select_set(state = False)
                
                
                ## Select and delete the flat proj_subject
                bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.select_all(action='DESELECT')
                if self.usinggeometric and self.intermarker and self.sequential:
                    collection = bpy.data.collections.get(f"{self.uniform_aruco_iter_del}.svg")
                    for obj in collection.objects:
                        bpy.data.objects.remove(obj, do_unlink=True)
                    bpy.data.collections.remove(collection)
                    self.uniform_aruco_iter_del += 1
                else:
                    codeobj.select_set(state = True)
                    bpy.context.view_layer.objects.active = codeobj
                    bpy.ops.object.delete()
                
                ## Calculate the average normal of the projected code
                ## Get world matrix
                world = projectioncode.matrix_world
                ## Get the average local norm of the new surface
                verts = projectioncode.data.vertices
                d = len(verts)
                x = sum(vert.normal[0] / d for vert in verts)
                y = sum(vert.normal[1] / d for vert in verts)
                z = sum(vert.normal[2] / d for vert in verts)
                locnorm = mathutils.Vector((x, y, z))
                ## Get the average global norm of the new surface
                norm = world @ locnorm 

                ####### EMBED AND EXTRUDE THE CODE #######
                
                ## Now extrude the code
                bpy.context.view_layer.objects.active = projectioncode   
                
                if self.customoffset:
                    shellthickness = self.offset
                if self.suggestoffset:
                    shellthickness = colordict[self.chosencolor][1]

                ## Embed the projected code
                projectioncode.location -= norm * shellthickness
                   
                ## Duplicate to make the extrusion a solid object      
                projectioncode.select_set(state = True)
                bpy.ops.object.duplicate_move()
                projectionback2 = bpy.context.object
                bpy.ops.object.select_all(action='DESELECT')
                
                ## Select the faces of the embedded code
                bpy.context.view_layer.objects.active = projectioncode
                bpy.ops.object.mode_set(mode="EDIT")
                projbm2 = get_bmesh(projectioncode)
                for face in projbm2.faces:
                    face.select = True
                ## Extrude
                if self.customoffset:
                    thick = self.thickness
                if self.suggestoffset:
                    thick = colordict[self.chosencolor][0]
                bpy.ops.mesh.extrude_faces_move(MESH_OT_extrude_faces_indiv={"mirror":False},\
                    TRANSFORM_OT_shrink_fatten={"value":-thick, "use_even_offset":False, "mirror":False, \
                    "use_proportional_edit":False, "proportional_edit_falloff":'SMOOTH', \
                    "proportional_size":1, "use_proportional_connected":False, \
                    "use_proportional_projected":False, "snap":False, "release_confirm":False, \
                    "use_accurate":False})
                
                ## Flip projectioncode's normals
                bpy.ops.object.mode_set(mode="EDIT")
                for face in get_bmesh(projectioncode).faces:
                    face.select = True
                bpy.ops.mesh.flip_normals()
                
                ## Join the extrusion and the duplicate back
                bpy.ops.object.mode_set(mode="OBJECT")
                obs = [projectioncode, projectionback2]
                with bpy.context.temp_override(active_object=bpy.context.active_object, selected_editable_objects=obs):
                    bpy.ops.object.join()

                ## Create the air gap
                bpy.context.view_layer.objects.active = projectioncode
                projectioncode.select_set(state = True)
                bpy.ops.object.duplicate_move()
                airgap = bpy.context.object
                airgap.name = f"Air Gap {iter + 1}"
                
                bpy.ops.object.mode_set(mode="EDIT")
                for face in get_bmesh(airgap).faces:
                    face.select = True
                bpy.ops.mesh.flip_normals()
                bpy.ops.object.mode_set(mode="OBJECT")

                ####### DELETE OBJECTS WE DON'T NEED ANYMORE #######
                
                
                
                bpy.ops.object.select_all(action='DESELECT')
                obj2.select_set(state = True)
                bpy.context.view_layer.objects.active = obj2
                bpy.ops.object.delete()
                
                iter += 1
            
        if self.usingman and not self.sequential:
            self.codemesh.select_set(state = True)
            bpy.context.view_layer.objects.active = self.codemesh
            bpy.ops.object.delete()
            
        for obj in bpy.data.objects:
            if len(obj.name) > 5:
                if obj.name[:6] == "Optima" or obj.name[:5] == "Patch" or obj.name[:13] == "Selected Regi":
                    bpy.data.objects.remove(obj, do_unlink=True)
                

        return {'FINISHED'}





 
def menu_func(self, context):
    self.layout.operator(OBJECT_OT_optimalembed.bl_idname)
    
def register():
    bpy.utils.register_class(OBJECT_OT_optimalembed)
    bpy.types.VIEW3D_MT_object.append(menu_func)
    
def unregister():
    bpy.utils.unregister_class(OBJECT_OT_optimalembed)
    bpy.types.VIEW3D_MT_object.remove(menu_func)
    
if __name__ == "__main__":
    register()
