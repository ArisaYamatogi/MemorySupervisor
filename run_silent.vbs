' ---------------------------------------------------------------------------
'  Memory Supervisor - silent launcher
'
'  Double-click this file (or a shortcut to it) to start the panel with no
'  console window at all, even if only python.exe is available.  It tries
'  pythonw.exe first and falls back to python.exe hidden behind a window-less
'  shell.
' ---------------------------------------------------------------------------
Option Explicit

Dim fso, shell, project, script, exe, args, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

project = fso.GetParentFolderName(WScript.ScriptFullName) & "\"
script = project & "memsup.py"

If Not fso.FileExists(script) Then
    MsgBox "memsup.py was not found next to this launcher:" & vbCrLf & script, _
           16, "Memory Supervisor"
    WScript.Quit 1
End If

exe = ""

' 1. a portable runtime shipped next to this file
If fso.FileExists(project & "runtime\pythonw.exe") Then
    exe = project & "runtime\pythonw.exe"
ElseIf fso.FileExists(project & "runtime\python.exe") Then
    exe = project & "runtime\python.exe"
End If

' 2. interpreter recorded in launcher.ini (written by the panel on first run)
If exe = "" Then
    Dim iniPath, ts, line
    iniPath = project & "launcher.ini"
    If fso.FileExists(iniPath) Then
        Set ts = fso.OpenTextFile(iniPath, 1)
        Do While Not ts.AtEndOfStream
            line = Trim(ts.ReadLine)
            If Len(line) > 7 Then
                If LCase(Left(line, 7)) = "python=" Then
                    line = Trim(Mid(line, 8))
                    If Len(line) > 0 Then
                        If fso.FileExists(line) Then exe = line
                    End If
                End If
            End If
        Loop
        ts.Close
    End If
End If

' 3. pythonw.exe / python.exe on PATH
If exe = "" Then
    Dim candidates, candidate
    candidates = Array("pythonw.exe", "python.exe")
    For Each candidate In candidates
        exe = FindOnPath(candidate)
        If exe <> "" Then Exit For
    Next
End If

If exe = "" Then
    MsgBox "Memory Supervisor could not find Python." & vbCrLf & vbCrLf & _
           "Install Python 3.8+ from python.org (tick ""Add python.exe to PATH"")" & _
           " or drop a portable Python into:" & vbCrLf & project & "runtime\", _
           16, "Memory Supervisor"
    WScript.Quit 1
End If

args = """" & script & """"
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

shell.Run """" & exe & """ " & args, 0, False


' Locate an executable on PATH without spawning a console.
Function FindOnPath(name)
    Dim fso2, shell2, dirs, d, full
    Set fso2 = CreateObject("Scripting.FileSystemObject")
    Set shell2 = CreateObject("WScript.Shell")
    FindOnPath = ""
    dirs = Split(shell2.ExpandEnvironmentStrings("%PATH%"), ";")
    For Each d In dirs
        If Len(Trim(d)) > 0 Then
            full = Trim(d) & "\" & name
            If fso2.FileExists(full) Then
                FindOnPath = full
                Exit Function
            End If
        End If
    Next
End Function
