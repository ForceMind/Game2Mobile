// SPDX-License-Identifier: MIT
using System.Windows.Forms;

namespace Game2Mobile.Operator.Windows;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
    }
}
