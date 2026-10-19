Libraries: 
    (1) os
    (2) pyrevit - DB, forms, script
    (3) shared_param_utils (another script - 4 other functions)

resolve_alt_sp_file takes two arguments: 
    (1) sp_file_value
    (2) primary_sp_dir

    Determines whether the file path of sp_file_value is absolute and whether it is a file or folder, then assigns variable 'candidate' to the 'joined' file path and file value, which will be determined to be correctly assigned or else the error of which the user will be prompted and the program will terminate

Lines 78-80 are global shortcuts to used to access the core Revit application and the active project document

    __revit__: The global instance of Autodesk.Revit.UI.UIApplication provided automatically in pyRevit's interactive/scripting environment.
    
    app (__revit__.Application): Returns the Autodesk.Revit.ApplicationServices.Application object, giving access to application-wide settings, shared parameters, and file-loading utilities.
    
    uidoc (__revit__.ActiveUIDocument): Returns the Autodesk.Revit.UI.UIDocument representing the user interface wrapper for the currently open project.
    
    doc (__revit__.ActiveUIDocument.Document): Navigates from the UI document down to the actual Autodesk.Revit.DB.Document database object, which lets you query, add, modify, or delete Revit elements (walls, floors, families, etc.)

The global variable REVIT_VERSION takes an integer of the (app.VersionNumber) of the current version of the Revit file, where key-value pairs of group names (of the desired parameters to be mapped listed within the CSV).
    For 2022 and later versions, the DB.GroupTypeId.[value] are enumerated values, meaning they are static 
    -I'm guessing 'set' is not an existing/native group name, so it creates it?  But fallback to 'construction' if set is not found?  

_get_revit_group takes the argument 'group_name' which 

