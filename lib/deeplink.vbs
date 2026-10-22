Dim sh, u, q
If WScript.Arguments.Count = 0 Then WScript.Quit 0
u = WScript.Arguments(0)
q = Chr(34)
Set sh = CreateObject("WScript.Shell")
sh.Run q & "C:\Program Files\nodejs\node.exe" & q & " " & q & "F:\IrisGoProxy\lib\deeplink.js" & q & " " & q & u & q, 0, False
