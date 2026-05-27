' run_raiv.vbs
' RAIV をコマンドウィンドウなしで起動する。
' なぜ存在するか: ユーザーがターミナルを表示せずにアプリを起動できるようにするため。
' 関連ファイル: raiv.py, run_raiv.bat

Option Explicit

Dim shell, fso, scriptDir, batchPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchPath = fso.BuildPath(scriptDir, "run_raiv.bat")
shell.CurrentDirectory = scriptDir
shell.Run """" & batchPath & """", 0, False
