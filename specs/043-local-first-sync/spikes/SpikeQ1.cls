Class Spike.Q1 Extends %RegisteredObject
{

ClassMethod Run()
{
    set ns = $namespace
    set $namespace = "%SYS"
    do ..Probe()
    set $namespace = ns
    quit
}

ClassMethod Probe()
{
    set seekOK = 0, seekHow = "", crossOK = 0, crossHow = ""
    set addr = "", gref = "", n = 0

    write !,"Q1.1 open the current journal file",!
    set jfName = ##class(%SYS.Journal.System).GetCurrentFileName()
    write "  current file: ",jfName,!
    set jf = ##class(%SYS.Journal.File).%OpenId(jfName)
    if '$isobject(jf) {
        write !,"Q1 VERDICT: INCONCLUSIVE -- could not open the current journal file",!
        quit
    }

    write !,"Q1.2 forward scan; capture an Address to seek back to",!
    set rec = jf.FirstRecord
    while $isobject(rec) && (n < 200) {
        set n = n + 1
        if n = 100 {
            try { set addr = rec.Address } catch e { write "  rec.Address unavailable: ",e.DisplayString(),! }
        }
        // Discriminate on the CLASS, not TypeName. TypeName is never the string
        // "SetKillRecord" -- on 2026.2 it takes values SET / KILL / ZKILL /
        // BeginTrans / CommitTrans. Gating GlobalReference on
        // TypeName="SetKillRecord" silently yields an empty global every time.
        if (gref = "") && ($classname(rec) [ "SetKillRecord") {
            try { set gref = rec.GlobalReference } catch e { }
        }
        set tn = "?"
        try { set tn = rec.TypeName } catch e { set tn = "?" }
        if $increment(seen(tn)) { }
        set rec = rec.Next
    }
    write "  walked ",n," records; captured Address = '",addr,"'",!
    if gref '= "" { write "  sample GlobalReference: ",gref,! }
    write "  record types seen: "
    set t = "" for { set t = $order(seen(t)) quit:t=""  write t,"=",seen(t),"  " }
    write !
    if ($data(seen("BeginTrans")) > 0) || ($data(seen("CommitTrans")) > 0) {
        write "  >> transaction boundaries ARE observable (BeginTrans/CommitTrans present)",!
    }
    if addr = "" {
        write !,"Q1 VERDICT: FAIL -- records expose no Address to resume from",!
        quit
    }

    write !,"Q1.3 probe seek-by-address candidates",!
    try {
        set r2 = ##class(%SYS.Journal.Record).%OpenId(addr)
        if $isobject(r2) {
            write "  [A] %SYS.Journal.Record.%OpenId(addr) -> OK, Address=",r2.Address,!
            if r2.Address = addr { set seekOK = 1, seekHow = "%SYS.Journal.Record.%OpenId(address)" }
        } else {
            write "  [A] %SYS.Journal.Record.%OpenId(addr) -> null",!
        }
    } catch e {
        write "  [A] failed: ",e.DisplayString(),!
    }
    if 'seekOK {
        try {
            set r2 = ##class(%SYS.Journal.Record).%OpenId(jfName_"||"_addr)
            if $isobject(r2) {
                write "  [B] %OpenId(file||addr) -> OK, Address=",r2.Address,!
                set seekOK = 1, seekHow = "%SYS.Journal.Record.%OpenId(file||address)"
            } else {
                write "  [B] %OpenId(file||addr) -> null",!
            }
        } catch e {
            write "  [B] failed: ",e.DisplayString(),!
        }
    }
    if 'seekOK {
        try {
            set r2 = jf.GetRecordAt(addr)
            if $isobject(r2) {
                write "  [C] jf.GetRecordAt(addr) -> OK, Address=",r2.Address,!
                set seekOK = 1, seekHow = "jf.GetRecordAt(address)"
            } else {
                write "  [C] jf.GetRecordAt(addr) -> null",!
            }
        } catch e {
            write "  [C] not available: ",e.DisplayString(),!
        }
    }
    if 'seekOK { write "  no seek candidate succeeded",! }

    write !,"Q1.4 probe cross-file iteration",!
    try {
        write "  [A] jf.Next = '",jf.Next,"'",!
        if jf.Next '= "" { set crossOK = 1, crossHow = "jf.Next" }
    } catch e {
        write "  [A] jf.Next not available: ",e.DisplayString(),!
    }
    try {
        write "  [B] jf.Prev = '",jf.Prev,"'",!
        if (jf.Prev '= "") && 'crossOK { set crossOK = 1, crossHow = "jf.Prev" }
    } catch e {
        write "  [B] jf.Prev not available: ",e.DisplayString(),!
    }
    try {
        set rs = ##class(%SQL.Statement).%ExecDirect(,"SELECT COUNT(*) AS n FROM %SYS_Journal.File")
        if (rs.%SQLCODE >= 0) && rs.%Next() {
            write "  [C] %SYS_Journal.File catalogue rows = ",rs.%Get("n"),!
            if 'crossOK { set crossOK = 1, crossHow = "%SYS_Journal.File catalogue query" }
        } else {
            write "  [C] catalogue query SQLCODE=",rs.%SQLCODE," (no such SQL projection)",!
        }
    } catch e {
        write "  [C] catalogue query failed: ",e.DisplayString(),!
    }
    // [D] is the one that works on 2026.2: the class's own ByTimeReverseOrder
    // query enumerates every journal file, newest first, with its size.
    try {
        set q = ##class(%ResultSet).%New("%SYS.Journal.File:ByTimeReverseOrder")
        set sc = q.Execute()
        set files = 0
        while q.Next() {
            set files = files + 1
            write "  [D] file: ",q.GetData(1),"  size=",q.GetData(2),!
        }
        write "  [D] ByTimeReverseOrder enumerated ",files," journal file(s)",!
        if files > 0 { set crossOK = 1, crossHow = "%SYS.Journal.File:ByTimeReverseOrder query" }
    } catch e {
        write "  [D] ByTimeReverseOrder failed: ",e.DisplayString(),!
    }

    write !,"Q1.5 throughput -- cold forward scan, up to 20000 records",!
    set t0 = $zh, rec = jf.FirstRecord, scanned = 0
    while $isobject(rec) && (scanned < 20000) {
        set scanned = scanned + 1
        set rec = rec.Next
    }
    set el = $zh - t0
    write "  scanned ",scanned," records in ",$fnumber(el,"",3),"s"
    if el > 0 { write "  (~",$fnumber(scanned/el,"",0)," rec/s)" }
    write !
    write "  This is the cost a NON-resumable reader pays on every poll.",!

    if seekOK && crossOK {
        set verdict = "PASS", note = "seek via "_seekHow_"; cross-file via "_crossHow
    } elseif seekOK {
        set verdict = "PASS", note = "seek via "_seekHow_" but no cross-file mechanism found"
    } else {
        set verdict = "FAIL", note = "no seek-by-address mechanism works; journal tailing is not resumable"
    }
    write !,"Q1 VERDICT: ",verdict," -- ",note,!
    quit
}

}
