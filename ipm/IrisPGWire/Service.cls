Class IrisPGWire.Service Extends %RegisteredObject
{

/// Global to store PID of running server
Parameter PIDGlobal = "^IrisPGWire.PID";

/// Global to store server status
Parameter StatusGlobal = "^IrisPGWire.Status";

/// The options Start() was last called with, so Restart() starts the server the same way.
Parameter OptionsGlobal = "^IrisPGWire.Options";

/// What the server logs once it is listening.
Parameter ReadyText = "PGWire server started";

/// Start the iris-pgwire TCP server.
/// <p>Clients must log in with an IRIS username and password, and the password is sent in the
/// clear, so the server refuses to start unless you choose how it is protected:
/// <ul>
/// <li><var>pSSLCert</var> and <var>pSSLKey</var>: TLS (recommended).</li>
/// <li><var>pAllowPlaintextPassword</var>: accept passwords over unencrypted connections, for a
/// trusted network or behind a TLS-terminating proxy.</li>
/// <li><var>pTrust</var>: no authentication at all. Local development only.</li>
/// </ul>
/// <var>pAllowedUsers</var> lists the IRIS users who may log in, comma-separated. Empty means the
/// service account alone. Statements run as the service account whoever logs in.
/// <p>Waits up to <var>pWaitSeconds</var> for the server to report that it is listening. If the
/// server exits first, the returned error carries the server's own reason.
/// <example>
/// Set sc = ##class(IrisPGWire.Service).Start(1)          // plaintext passwords, trusted network
/// Set sc = ##class(IrisPGWire.Service).Start(0,,,"/certs/pgwire.pem","/certs/pgwire.key")  // TLS
/// </example>
ClassMethod Start(pAllowPlaintextPassword As %Boolean = 0, pTrust As %Boolean = 0, pAllowedUsers As %String = "", pSSLCert As %String = "", pSSLKey As %String = "", pPort As %String = 5432, pWaitSeconds As %Integer = 60) As %Status
{
    Set tSC = $$$OK
    Try {
        If ..GetStatus() = "running" {
            Write !,"iris-pgwire server is already running (PID: ", @..#PIDGlobal, ")",!
            Quit
        }

        Set tSC = ..BuildCommand(pAllowPlaintextPassword, pTrust, pAllowedUsers, pSSLCert, pSSLKey, pPort, .tCommand, .tLogFile)
        Quit:$$$ISERR(tSC)

        Write !,"Starting iris-pgwire on port ", pPort, "...",!

        // A fresh log, so the readiness and refusal checks below read only this start.
        Do ##class(%Library.File).Delete(tLogFile)

        // $ZF(-100) runs the command and returns when the shell exits, which is at once: only the
        // server is backgrounded. The shell writes the server's PID to its stdout, kept in a file.
        // (The previous code used %Library.Pipe, which does not exist in IRIS 2026.)
        Set tPIDFile = tLogFile _ ".pid"
        Do ##class(%Library.File).Delete(tPIDFile)
        Set tExit = $ZF(-100, "/STDOUT=""" _ tPIDFile _ """", "/bin/sh", "-c", tCommand)
        Set tPID = ..FirstLine(tPIDFile)
        Do ##class(%Library.File).Delete(tPIDFile)
        If tExit '= 0 {
            Set tSC = $$$ERROR($$$GeneralError, "Failed to launch iris-pgwire (shell exit " _ tExit _ "): " _ ..LogTail(tLogFile, 3))
            Quit
        }

        If (tPID = "") || (tPID '= +tPID) {
            Set tSC = $$$ERROR($$$GeneralError, "Failed to start server - invalid PID: " _ tPID)
            Quit
        }

        // Wait until the server says it is listening, or exits.
        Set tReady = 0
        Set tExited = 0
        For tI = 1:1:(pWaitSeconds * 2) {
            Hang 0.5
            If ..LogContains(tLogFile, ..#ReadyText) {
                Set tReady = 1
                Quit
            }
            If '..IsProcessRunning(tPID) {
                Set tExited = 1
                Quit
            }
        }

        If tExited {
            Set tSC = $$$ERROR($$$GeneralError, "iris-pgwire did not start: " _ ..LogTail(tLogFile, 3) _ " (log: " _ tLogFile _ ")")
            Quit
        }

        // Record it either way, so Stop() can reach a server that is slow to come up.
        Set @..#PIDGlobal = tPID
        Set @..#StatusGlobal = "running"
        Set @..#OptionsGlobal = $ListBuild(pAllowPlaintextPassword, pTrust, pAllowedUsers, pSSLCert, pSSLKey, pPort, pWaitSeconds)

        If 'tReady {
            Set tSC = $$$ERROR($$$GeneralError, "iris-pgwire is running (PID " _ tPID _ ") but did not report that it is listening within " _ pWaitSeconds _ " seconds. Check " _ tLogFile)
            Quit
        }

        Write "iris-pgwire started. PID: ", tPID, ", port: ", pPort, ", log: ", tLogFile,!
        If pTrust {
            Write "WARNING: authentication is disabled (pTrust). Every client is accepted.",!
        }

    } Catch ex {
        Set tSC = ex.AsStatus()
    }

    If $$$ISERR(tSC) {
        Write !,"Error starting iris-pgwire: ", $SYSTEM.Status.GetErrorText(tSC),!
    }
    Quit tSC
}

/// Build the shell command that starts the server, after checking every value that reaches it.
/// <p>Nothing caller-supplied reaches the shell unchecked: the users list and the port are
/// restricted to safe characters, and the certificate paths must exist and contain no quote.
/// The command changes into the package directory first, because irispython does not honour
/// PYTHONPATH and IPM installs the package outside its default path.
ClassMethod BuildCommand(pAllowPlaintextPassword As %Boolean, pTrust As %Boolean, pAllowedUsers As %String, pSSLCert As %String, pSSLKey As %String, pPort As %String, Output pCommand As %String, Output pLogFile As %String) As %Status
{
    Set tSC = $$$OK
    Set pCommand = ""
    Set pLogFile = ""
    Try {
        If (pPort = "") || ($ZStrip(pPort, "*N") '= "") || (pPort < 1) || (pPort > 65535) {
            Set tSC = $$$ERROR($$$GeneralError, "pPort must be a number from 1 to 65535, got: " _ pPort)
            Quit
        }

        // Letters, digits and , . _ % - only: these are IRIS user names, and the value is passed on
        // a shell command line.
        If $ZStrip(pAllowedUsers, "*AN", ",._%-") '= "" {
            Set tSC = $$$ERROR($$$GeneralError, "pAllowedUsers may contain only letters, digits and , . _ % -")
            Quit
        }

        If (pSSLCert = "") '= (pSSLKey = "") {
            Set tSC = $$$ERROR($$$GeneralError, "Give both pSSLCert and pSSLKey, or neither")
            Quit
        }
        For tPath = pSSLCert, pSSLKey {
            Continue:tPath=""
            If tPath [ "'" {
                Set tSC = $$$ERROR($$$GeneralError, "Certificate and key paths may not contain a quote: " _ tPath)
                Quit
            }
            If '##class(%Library.File).Exists(tPath) {
                Set tSC = $$$ERROR($$$GeneralError, "File not found: " _ tPath)
                Quit
            }
        }
        Quit:$$$ISERR(tSC)

        Set tPackageDir = ##class(%Library.File).NormalizeDirectory($SYSTEM.Util.InstallDirectory() _ "mgr/python/iris-pgwire/")
        If '##class(%Library.File).DirectoryExists(tPackageDir _ "iris_pgwire") {
            Set tSC = $$$ERROR($$$GeneralError, "iris-pgwire package not found in: " _ tPackageDir)
            Quit
        }
        Set pLogFile = $SYSTEM.Util.InstallDirectory() _ "mgr/iris-pgwire.log"
        Set tPython = ##class(%Library.File).NormalizeFilename($SYSTEM.Util.BinaryDirectory() _ "irispython")

        Set tEnv = "PGWIRE_PORT=" _ pPort
        If pSSLCert '= "" {
            Set tEnv = tEnv _ " PGWIRE_SSL_ENABLED=true PGWIRE_SSL_CERT='" _ pSSLCert _ "' PGWIRE_SSL_KEY='" _ pSSLKey _ "'"
        }

        Set tArgs = ""
        If pTrust {
            Set tArgs = tArgs _ " --trust"
        }
        If pAllowPlaintextPassword {
            Set tArgs = tArgs _ " --allow-plaintext-password"
        }
        If pAllowedUsers '= "" {
            Set tArgs = tArgs _ " --allowed-users " _ pAllowedUsers
        }

        // `cd` in this shell, then background only the server, so $! is the server's own PID.
        Set pCommand = "cd '" _ tPackageDir _ "' && { " _ tEnv _ " nohup '" _ tPython _ "' -m iris_pgwire.server" _ tArgs _ " > '" _ pLogFile _ "' 2>&1 & echo $!; }"

    } Catch ex {
        Set tSC = ex.AsStatus()
    }
    Quit tSC
}

/// Stop the iris-pgwire TCP server.
/// Called during IPM Deactivate phase.
/// <p>Sends SIGTERM, which the server handles by closing its listener and connections, then
/// SIGKILL if it is still running after <var>pGraceSeconds</var>.
ClassMethod Stop(pGraceSeconds As %Integer = 10) As %Status
{
    Set tSC = $$$OK
    Try {
        If ..GetStatus() '= "running" {
            Write !,"iris-pgwire server is not running",!
            Quit
        }

        Set tPID = @..#PIDGlobal
        Write !,"Stopping iris-pgwire server (PID: ", tPID, ")...",!

        Do $ZF(-100, "", "/bin/kill", "-TERM", tPID)
        Set tGone = ..WaitForExit(tPID, pGraceSeconds)

        If 'tGone {
            Write "Still running after ", pGraceSeconds, " seconds; sending SIGKILL",!
            Do $ZF(-100, "", "/bin/kill", "-KILL", tPID)
            Set tGone = ..WaitForExit(tPID, 5)
        }

        If 'tGone {
            Set tSC = $$$ERROR($$$GeneralError, "Failed to stop iris-pgwire (PID " _ tPID _ ")")
            Quit
        }

        Kill @..#PIDGlobal
        Set @..#StatusGlobal = "stopped"
        Write "iris-pgwire stopped",!

    } Catch ex {
        Set tSC = ex.AsStatus()
        Write !,"Error stopping iris-pgwire: ", $SYSTEM.Status.GetErrorText(tSC),!
    }

    Quit tSC
}

/// Restart the server with the options it was last started with.
ClassMethod Restart() As %Status
{
    Set tSC = ..Stop()
    If $$$ISERR(tSC) {
        Quit tSC
    }

    Set tOptions = $Get(@..#OptionsGlobal)
    If tOptions = "" {
        Quit $$$ERROR($$$GeneralError, "No previous Start() options to restart with; call Start() with the options you want")
    }

    Quit ..Start($ListGet(tOptions, 1), $ListGet(tOptions, 2), $ListGet(tOptions, 3), $ListGet(tOptions, 4), $ListGet(tOptions, 5), $ListGet(tOptions, 6, 5432), $ListGet(tOptions, 7, 60))
}

/// Get current server status
/// Returns: "running" or "stopped"
ClassMethod GetStatus() As %String
{
    If '$Data(@..#PIDGlobal) {
        Quit "stopped"
    }

    Set tPID = @..#PIDGlobal
    If ..IsProcessRunning(tPID) {
        Quit "running"
    }

    // PID recorded but the process is gone: clean up
    Kill @..#PIDGlobal
    Set @..#StatusGlobal = "stopped"
    Quit "stopped"
}

/// The PID of the running server, or "" when it is not running.
ClassMethod GetPID() As %String
{
    If ..GetStatus() '= "running" {
        Quit ""
    }
    Quit @..#PIDGlobal
}

/// Check if a process is running
/// Returns: 1 if running, 0 if not
ClassMethod IsProcessRunning(pPID As %String) As %Boolean
{
    If (pPID = "") || (pPID '= +pPID) {
        Quit 0
    }
    // kill -0 tests for the process without sending it a signal
    Quit ($ZF(-100, "/STDERR=""/dev/null""", "/bin/kill", "-0", pPID) = 0)
}

/// Wait up to pSeconds for pPID to exit. Returns 1 once it has.
ClassMethod WaitForExit(pPID As %String, pSeconds As %Integer) As %Boolean
{
    Set tGone = 0
    For tI = 1:1:(pSeconds * 2) {
        If '..IsProcessRunning(pPID) {
            Set tGone = 1
            Quit
        }
        Hang 0.5
    }
    If 'tGone {
        Set tGone = '..IsProcessRunning(pPID)
    }
    Quit tGone
}

/// The first line of pFile with surrounding whitespace removed, or "" if there is none.
ClassMethod FirstLine(pFile As %String) As %String
{
    Set tStream = ##class(%Stream.FileCharacter).%New()
    Set tSC = tStream.LinkToFile(pFile)
    If $$$ISERR(tSC) || tStream.AtEnd {
        Quit ""
    }
    Quit $ZStrip(tStream.ReadLine(), "<>W")
}

/// True if any line of pLogFile contains pText.
ClassMethod LogContains(pLogFile As %String, pText As %String) As %Boolean
{
    Set tFound = 0
    Set tStream = ##class(%Stream.FileCharacter).%New()
    Set tSC = tStream.LinkToFile(pLogFile)
    If $$$ISERR(tSC) {
        Quit 0
    }
    While 'tStream.AtEnd {
        If $Find(tStream.ReadLine(), pText) {
            Set tFound = 1
            Quit
        }
    }
    Quit tFound
}

/// The last pLines non-empty lines of pLogFile, joined, with terminal colour codes removed.
ClassMethod LogTail(pLogFile As %String, pLines As %Integer = 3) As %String
{
    Set tCount = 0
    Set tStream = ##class(%Stream.FileCharacter).%New()
    Set tSC = tStream.LinkToFile(pLogFile)
    If $$$ISERR(tSC) {
        Quit "(no log at " _ pLogFile _ ")"
    }
    While 'tStream.AtEnd {
        Set tLine = $ZStrip(..StripColour(tStream.ReadLine()), "<>W")
        If tLine '= "" {
            Set tCount = tCount + 1
            Set tLines(tCount) = tLine
        }
    }
    Set tTail = ""
    For tI = $Select(tCount > pLines: (tCount - pLines) + 1, 1: 1):1:tCount {
        Set tTail = tTail _ $Select(tTail = "": "", 1: " | ") _ tLines(tI)
    }
    Quit $Select(tTail = "": "(log is empty)", 1: tTail)
}

/// Remove ANSI colour sequences (ESC [ ... m) from a log line.
ClassMethod StripColour(pLine As %String) As %String
{
    Set tOut = ""
    Set tPos = 1
    For {
        Set tEsc = $Find(pLine, $Char(27) _ "[", tPos)
        If tEsc = 0 {
            Set tOut = tOut _ $Extract(pLine, tPos, *)
            Quit
        }
        Set tOut = tOut _ $Extract(pLine, tPos, tEsc - 3)
        Set tEnd = $Find(pLine, "m", tEsc)
        If tEnd = 0 {
            Quit
        }
        Set tPos = tEnd
    }
    Quit tOut
}

/// Display server status information
ClassMethod ShowStatus()
{
    Set tStatus = ..GetStatus()

    Write !,"iris-pgwire Server Status",!
    Write "========================",!
    Write "Status: ", tStatus,!

    If tStatus = "running" {
        Write "PID: ", @..#PIDGlobal,!
        Set tOptions = $Get(@..#OptionsGlobal)
        If tOptions '= "" {
            Write "Port: ", $ListGet(tOptions, 6, 5432),!
        }
        Write "Recent log: ", ..LogTail($SYSTEM.Util.InstallDirectory() _ "mgr/iris-pgwire.log", 5),!
    }

    Write !
}

}
