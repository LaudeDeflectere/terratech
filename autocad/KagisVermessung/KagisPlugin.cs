using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;

// Loads the plug-in in AutoCAD and registers the command class.
[assembly: ExtensionApplication(typeof(KagisVermessung.KagisPlugin))]
[assembly: CommandClass(typeof(KagisVermessung.KagisCommands))]

namespace KagisVermessung
{
    public class KagisPlugin : IExtensionApplication
    {
        public void Initialize()
        {
            var doc = Autodesk.AutoCAD.ApplicationServices.Application.DocumentManager.MdiActiveDocument;
            doc?.Editor.WriteMessage("\nKagisVermessung loaded. Type KAGISVERMESSUNG to start.\n");
        }

        public void Terminate()
        {
        }
    }
}
