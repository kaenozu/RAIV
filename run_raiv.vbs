' run_raiv.vbs
' RAIV をコマンドウィンドウなしで起動する。
' なぜ存在するか: ユーザーがターミナルを表示せずにアプリを起動できるようにするため。
' 関連ファイル: raiv.py, run_raiv.bat

Option Explicit

Dim shell, fso, scriptDir, batchPath, argsText, i, arg
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchPath = fso.BuildPath(scriptDir, "run_raiv.bat")
shell.CurrentDirectory = scriptDir
argsText = ""
For i = 0 To WScript.Arguments.Count - 1
	arg = WScript.Arguments(i)
	arg = Replace(arg, """", """""")
	argsText = argsText & " """ & arg & """"
Next
shell.Run """" & batchPath & """" & argsText, 0, False
