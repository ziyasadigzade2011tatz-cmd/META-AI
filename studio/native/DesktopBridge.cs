using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

class DesktopBridge {
 delegate bool EnumProc(IntPtr hwnd, IntPtr data);
 [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback,IntPtr data);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
 [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd,StringBuilder text,int max);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
 [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd,out Rect rect);
 [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd,IntPtr dc,uint flags);
 [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
 [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd,int command);
 [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
 [StructLayout(LayoutKind.Sequential)] struct Rect { public int Left,Top,Right,Bottom; }
 static readonly JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=12000000 };
 static Dictionary<string,object> Describe(IntPtr hwnd) {
  if(!IsWindowVisible(hwnd)) return null;
  var title=new StringBuilder(1024);GetWindowText(hwnd,title,title.Capacity);
  if(title.Length==0)return null;
  uint pid;GetWindowThreadProcessId(hwnd,out pid);string app="";
  try {app=Process.GetProcessById((int)pid).ProcessName;} catch {return null;}
  return new Dictionary<string,object>{{"id",hwnd.ToInt64().ToString("x")},{"pid",pid},{"title",title.ToString()},{"app",app},{"minimized",IsIconic(hwnd)}};
 }
 static void Output(object value){Console.WriteLine(Json.Serialize(value));}
 [STAThread] static int Main(string[] args) {
  Console.OutputEncoding=new UTF8Encoding(false);
  SetProcessDPIAware();
  try {
   if(args.Length==1 && args[0]=="list") {
    var windows=new List<Dictionary<string,object>>();EnumWindows(delegate(IntPtr hwnd,IntPtr data){var row=Describe(hwnd);if(row!=null)windows.Add(row);return windows.Count<200;},IntPtr.Zero);
    Output(new { windows=windows });return 0;
   }
   if(args.Length!=3 || (args[0]!="activate" && args[0]!="capture"))throw new Exception("Unknown operation");
   long number;if(!long.TryParse(args[1],System.Globalization.NumberStyles.HexNumber,null,out number))throw new Exception("Invalid window");
   var target=new IntPtr(number);var info=Describe(target);
   if(info==null || info["pid"].ToString()!=args[2])throw new Exception("Window changed");
   string app=((string)info["app"]).ToLowerInvariant();string title=((string)info["title"]).ToLowerInvariant();
   if(app.Contains("keepass")||app.Contains("1password")||app.Contains("bitwarden")||app=="credentialuibroker"||title.Contains("windows security")||title.Contains("безопасность windows"))throw new Exception("Protected window; use it manually");
   if(args[0]=="activate") {ShowWindow(target,9);bool ok=SetForegroundWindow(target);Output(new { activated=ok });return 0;}
   if(IsIconic(target))throw new Exception("Restore the window before capture");
   Rect rect;if(!GetWindowRect(target,out rect))throw new Exception("Window size unavailable");
   int width=rect.Right-rect.Left,height=rect.Bottom-rect.Top;
   if(width<10||height<10||width>8192||height>8192||(long)width*height>20000000)throw new Exception("Unsupported window size");
   using(var bitmap=new Bitmap(width,height)) {
    using(var graphics=Graphics.FromImage(bitmap)) {IntPtr dc=graphics.GetHdc();try {if(!PrintWindow(target,dc,2))throw new Exception("Window does not support capture");} finally {graphics.ReleaseHdc(dc);}}
    int min=255,max=0;
    for(int y=0;y<height;y+=Math.Max(1,height/20))for(int x=0;x<width;x+=Math.Max(1,width/20)){Color c=bitmap.GetPixel(x,y);int v=(c.R+c.G+c.B)/3;min=Math.Min(min,v);max=Math.Max(max,v);}
    if(max-min<3)throw new Exception("Window returned an empty image; use a manual screenshot");
    double scale=Math.Min(1.0,Math.Min(1600.0/width,1100.0/height));
    using(var resized=new Bitmap(Math.Max(1,(int)(width*scale)),Math.Max(1,(int)(height*scale)))) {
     using(var g=Graphics.FromImage(resized)){g.InterpolationMode=System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;g.DrawImage(bitmap,0,0,resized.Width,resized.Height);}
     using(var stream=new MemoryStream()){resized.Save(stream,ImageFormat.Png);if(stream.Length>4500000)throw new Exception("Image too large");Output(new { image="data:image/png;base64,"+Convert.ToBase64String(stream.ToArray()),width=resized.Width,height=resized.Height });}
    }
   }
   return 0;
  } catch(Exception ex){Output(new { error=ex.Message });return 1;}
 }
}
