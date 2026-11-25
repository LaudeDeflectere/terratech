using System.IO;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;

namespace KagisVermessung
{
    public class KagisCommands
    {
        /// <summary>
        /// KAGISVERMESSUNG: pick an area on the KAGIS map, download the DGM tiles,
        /// convert them to 1 m contours and insert the contours into the drawing.
        /// </summary>
        [CommandMethod("KagisVermessung", CommandFlags.Modal)]
        public void KagisVermessungCommand()
        {
            Document doc = AcApp.DocumentManager.MdiActiveDocument;
            if (doc == null) return;
            Editor ed = doc.Editor;

            try
            {
                using (var form = new PickerForm())
                {
                    System.Windows.Forms.DialogResult answer = AcApp.ShowModalDialog(form);
                    if (answer != System.Windows.Forms.DialogResult.OK || string.IsNullOrEmpty(form.ResultDxfPath))
                    {
                        ed.WriteMessage("\nKagisVermessung: cancelled. Nothing was inserted.\n");
                        return;
                    }

                    if (!File.Exists(form.ResultDxfPath))
                        throw new FileNotFoundException("The contour file was not created.", form.ResultDxfPath);

                    InsertDxf(doc, form.ResultDxfPath);
                    ed.Regen();
                    ed.WriteMessage(
                        $"\nKagisVermessung: {form.ResultContourCount:N0} contours inserted. " +
                        $"Source: {form.ResultDxfPath}\n" +
                        "Coordinates are EPSG:31258 (metres). The drawing must use the same coordinates.\n");
                }
            }
            catch (System.Exception ex)
            {
                ed.WriteMessage($"\nKagisVermessung failed: {ex.Message}\n");
            }
        }

        /// <summary>Inserts the model space of the contour DXF into the current drawing.</summary>
        internal static void InsertDxf(Document doc, string dxfPath)
        {
            using (doc.LockDocument())
            using (var source = new Database(false, true))
            {
                source.DxfIn(dxfPath, null);
                doc.Database.Insert(Matrix3d.Identity, source, false);
            }
        }
    }
}
