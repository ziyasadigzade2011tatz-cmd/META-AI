using System;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Security.Cryptography;
using System.Reflection;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Threading.Tasks;

class Setup : Form {
 TextBox target; Button install; ProgressBar progress; Label status; CheckBox shortcut,launch;
 const string Version="5.3.1";
 Setup(){
  Text="META Studio · Установка "+Version;ClientSize=new Size(690,450);StartPosition=FormStartPosition.CenterScreen;BackColor=Color.FromArgb(35,36,39);ForeColor=Color.FromArgb(237,234,225);Font=new Font("Segoe UI",10);FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;
  Controls.Add(new Label{Text="ᴍ  META Studio",Font=new Font("Segoe UI",26,FontStyle.Bold),ForeColor=Color.FromArgb(220,149,93),Location=new Point(30,25),Size=new Size(600,60)});
  Controls.Add(new Label{Text="Твоё пространство для идей и кода",Location=new Point(34,92),Size=new Size(620,28)});
  Controls.Add(new Label{Text="Папка приложения",Location=new Point(34,140),Size=new Size(550,25)});
  string current=@"C:\Users\Desktop\META_FULL_DESKTOP\META-Next";
  target=new TextBox{Text=Directory.Exists(current)?current:Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","META"),Location=new Point(34,170),Size=new Size(530,28)};Controls.Add(target);
  Button browse=new Button{Text="Обзор…",Location=new Point(574,167),Size=new Size(85,32)};browse.Click+=(s,e)=>{using(FolderBrowserDialog dialog=new FolderBrowserDialog()){dialog.SelectedPath=target.Text;if(dialog.ShowDialog()==DialogResult.OK)target.Text=dialog.SelectedPath;}};Controls.Add(browse);
  shortcut=new CheckBox{Text="Создать ярлык META на рабочем столе",Checked=true,Location=new Point(34,215),Size=new Size(600,28)};Controls.Add(shortcut);
  launch=new CheckBox{Text="Запустить META после установки",Checked=true,Location=new Point(34,245),Size=new Size(600,28)};Controls.Add(launch);
  Controls.Add(new Label{Text="Чаты, память и модели не переносятся и не удаляются.\nДля генерации нужны отдельно установленная Ollama и скачанная модель.",ForeColor=Color.Silver,Location=new Point(34,287),Size=new Size(620,45)});
  progress=new ProgressBar{Location=new Point(34,345),Size=new Size(620,8)};Controls.Add(progress);
  status=new Label{Text="Готово к установке. Резервные копии не создаются.",Location=new Point(34,365),Size=new Size(430,50)};Controls.Add(status);
  install=new Button{Text="Установить / обновить",BackColor=Color.FromArgb(220,149,93),ForeColor=Color.Black,FlatStyle=FlatStyle.Flat,Location=new Point(460,370),Size=new Size(200,43)};Controls.Add(install);
  install.Click+=async(s,e)=>{string folder=target.Text;bool makeShortcut=shortcut.Checked,run=launch.Checked;install.Enabled=false;try{await Task.Run(()=>Install(folder,makeShortcut,(n,total)=>BeginInvoke(new Action(()=>{progress.Maximum=Math.Max(1,total);progress.Value=Math.Min(n,progress.Maximum);status.Text="Установка файлов… "+n+" / "+total;}))));status.Text="META Studio "+Version+" установлена.";if(run)Process.Start(new ProcessStartInfo(Path.Combine(folder,"META-Next.exe")){WorkingDirectory=folder,UseShellExecute=true});MessageBox.Show("Установка завершена. Данные сохранены.\nЕсли Ollama отсутствует: https://ollama.com/download/windows\nМодель: ollama pull qwen3.5:4b", "META Studio");Close();}catch(Exception ex){status.Text="Установка не завершена.";MessageBox.Show(ex.Message,"META Studio",MessageBoxButtons.OK,MessageBoxIcon.Error);install.Enabled=true;}};
 }
 static string Hash(Stream stream){using(SHA256 sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();}
 static void ValidateRoot(string folder){
  folder=Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar);
  string home=Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
  foreach(Environment.SpecialFolder special in new[]{Environment.SpecialFolder.DesktopDirectory,Environment.SpecialFolder.MyDocuments,Environment.SpecialFolder.LocalApplicationData,Environment.SpecialFolder.ApplicationData})if(folder.Equals(Environment.GetFolderPath(special).TrimEnd((char)92),StringComparison.OrdinalIgnoreCase))throw new Exception("Выбери отдельную папку META, а не весь рабочий стол или каталог документов.");
  if(folder.Length<8||folder.Equals(home,StringComparison.OrdinalIgnoreCase)||folder.Equals(Path.GetPathRoot(folder).TrimEnd((char)92),StringComparison.OrdinalIgnoreCase))throw new Exception("Выбери отдельную папку приложения.");
  for(DirectoryInfo p=new DirectoryInfo(folder);p!=null;p=p.Parent)if(p.Exists&&(p.Attributes&FileAttributes.ReparsePoint)!=0)throw new Exception("Папка со ссылкой/junction не поддерживается.");
  string[] protectedRoots={Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"META"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"META Next Preview"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"META Profiles"),Path.Combine(home,".ollama"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","Ollama"),@"D:\META\Models",@"D:\META\secrets",@"D:\META\Core"};
  foreach(string root in protectedRoots){string full=Path.GetFullPath(root).TrimEnd((char)92);if(folder.Equals(full,StringComparison.OrdinalIgnoreCase)||folder.StartsWith(full+"\\",StringComparison.OrdinalIgnoreCase)||full.StartsWith(folder+"\\",StringComparison.OrdinalIgnoreCase))throw new Exception("Это защищённая папка данных, моделей или Core. Выбери папку приложения.");}
 }
 static void Install(string folder,bool shortcut,Action<int,int> update){
  folder=Path.GetFullPath(folder);ValidateRoot(folder);string exe=Path.Combine(folder,"META-Next.exe");
  foreach(Process p in Process.GetProcesses()){bool running=false;try{running=String.Equals(p.MainModule.FileName,exe,StringComparison.OrdinalIgnoreCase);}catch{}if(running)throw new InvalidOperationException("Закрой META через Exit META, затем повтори установку.");}
  using(Stream payload=Assembly.GetExecutingAssembly().GetManifestResourceStream("META.Payload.zip"))using(ZipArchive zip=new ZipArchive(payload,ZipArchiveMode.Read)){
   Dictionary<string,string> hashes=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);using(StreamReader reader=new StreamReader(zip.GetEntry("payload.sha256").Open(),Encoding.UTF8)){string line;while((line=reader.ReadLine())!=null){if(line.Length<66)continue;hashes.Add(line.Substring(66),line.Substring(0,64));}}
   // Verify every entry before writing any application file.
   foreach(ZipArchiveEntry entry in zip.Entries){if(entry.FullName=="payload.sha256")continue;string destination=Path.GetFullPath(Path.Combine(folder,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));if(!destination.StartsWith(folder.TrimEnd((char)92)+"\\",StringComparison.OrdinalIgnoreCase))throw new Exception("Недопустимый путь в пакете.");for(string check=destination;check!=null&&check.Length>=folder.Length;check=Path.GetDirectoryName(check)){if((File.Exists(check)||Directory.Exists(check))&&(File.GetAttributes(check)&FileAttributes.ReparsePoint)!=0)throw new Exception("Ссылка внутри папки установки запрещена.");}if(!hashes.ContainsKey(entry.FullName))throw new Exception("Файл отсутствует в манифесте.");using(Stream stream=entry.Open())if(Hash(stream)!=hashes[entry.FullName])throw new Exception("Проверка пакета не пройдена.");}
   Directory.CreateDirectory(folder);int n=0;
   foreach(ZipArchiveEntry entry in zip.Entries){if(entry.FullName=="payload.sha256")continue;string destination=Path.GetFullPath(Path.Combine(folder,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));Directory.CreateDirectory(Path.GetDirectoryName(destination));if(File.Exists(destination))File.SetAttributes(destination,FileAttributes.Normal);using(Stream input=entry.Open())using(FileStream output=new FileStream(destination,FileMode.Create,FileAccess.Write))input.CopyTo(output);using(FileStream verify=File.OpenRead(destination))if(Hash(verify)!=hashes[entry.FullName])throw new Exception("Проверка установленного файла не пройдена.");update(++n,hashes.Count);}
   PruneFrontend(folder,hashes);
   File.WriteAllText(Path.Combine(folder,".meta-install.txt"),"META Studio "+Version+"\n"+DateTime.UtcNow.ToString("o"),new UTF8Encoding(false));
  }
  if(shortcut){MakeShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"META-Next.lnk"),exe,folder);string menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),"Programs","META");Directory.CreateDirectory(menu);MakeShortcut(Path.Combine(menu,"META Studio.lnk"),exe,folder);}
 }
 static void PruneFrontend(string folder,Dictionary<string,string> hashes){
  string root=Path.Combine(folder,"_internal","frontend","dist");if(!Directory.Exists(root))return;
  Stack<string> pending=new Stack<string>();pending.Push(root);
  while(pending.Count>0){string current=pending.Pop();if((File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)continue;
   foreach(string directory in Directory.GetDirectories(current))if((File.GetAttributes(directory)&FileAttributes.ReparsePoint)==0)pending.Push(directory);
   foreach(string file in Directory.GetFiles(current)){if((File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0)continue;string relative=file.Substring(folder.TrimEnd((char)92).Length+1).Replace((char)92,'/');string extension=Path.GetExtension(file).ToLowerInvariant();if(!hashes.ContainsKey(relative)&&Array.IndexOf(new[]{".js",".css",".ttf",".svg",".html",".map"},extension)>=0){File.SetAttributes(file,FileAttributes.Normal);File.Delete(file);}}
  }
 }
 static void MakeShortcut(string path,string exe,string folder){Type type=Type.GetTypeFromProgID("WScript.Shell");object shell=Activator.CreateInstance(type);object link=type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{path});Type lt=link.GetType();lt.InvokeMember("TargetPath",BindingFlags.SetProperty,null,link,new object[]{exe});lt.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,link,new object[]{folder});lt.InvokeMember("Description",BindingFlags.SetProperty,null,link,new object[]{"META Studio "+Version});lt.InvokeMember("Save",BindingFlags.InvokeMethod,null,link,null);}
 [STAThread]static int Main(string[] args){
  if(args.Length>=2&&args[0]=="--install-to"){try{Install(args[1],false,(n,total)=>{});Console.WriteLine("Installed and payload hashes verified.");return 0;}catch(Exception ex){Console.Error.WriteLine(ex.Message);return 1;}}
  Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new Setup());return 0;
 }
}
