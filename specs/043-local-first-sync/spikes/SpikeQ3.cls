Class Spike.Q3 Extends %RegisteredObject
{

ClassMethod Run()
{
    set ROWS = %%ROWS%%
    set verdict = "INCONCLUSIVE", note = "probe did not complete"

    write !,"Q3.1 setup -- two tables, one with an outbox trigger",!
    set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ3A")
    set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ3B")
    kill ^PGWireSync.Log, ^PGWireSync.Seq

    set rs = ##class(%SQL.Statement).%ExecDirect(,"CREATE TABLE SQLUser.SpikeQ3A (id INT PRIMARY KEY, payload VARCHAR(100))")
    if rs.%SQLCODE < 0 {
        write "  create A failed: ",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q3 VERDICT: INCONCLUSIVE -- could not create baseline table",!
        quit
    }
    set rs = ##class(%SQL.Statement).%ExecDirect(,"CREATE TABLE SQLUser.SpikeQ3B (id INT PRIMARY KEY, payload VARCHAR(100))")
    if rs.%SQLCODE < 0 {
        write "  create B failed: ",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q3 VERDICT: INCONCLUSIVE -- could not create trigger table",!
        quit
    }
    write "  tables created",!

    set tsql = "CREATE TRIGGER SpikeQ3BOutbox AFTER INSERT ON SQLUser.SpikeQ3B "
    set tsql = tsql_"FOR EACH ROW LANGUAGE OBJECTSCRIPT "
    set tsql = tsql_"{ SET ^PGWireSync.Log($INCREMENT(^PGWireSync.Seq)) = $LISTBUILD(""SpikeQ3B"",""insert"",{id}) }"
    set rs = ##class(%SQL.Statement).%ExecDirect(,tsql)
    if rs.%SQLCODE < 0 {
        write "  CREATE TRIGGER failed: SQLCODE=",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q3 VERDICT: INCONCLUSIVE -- trigger could not be created",!
        quit
    }
    write "  trigger created",!

    write !,"Q3.2 baseline -- ",ROWS," inserts, no trigger",!
    set stA = ##class(%SQL.Statement).%New()
    set sc = stA.%Prepare("INSERT INTO SQLUser.SpikeQ3A (id,payload) VALUES (?,?)")
    if '$system.Status.IsOK(sc) {
        write "  prepare failed: ",$system.Status.GetErrorText(sc),!
        write !,"Q3 VERDICT: INCONCLUSIVE -- could not prepare baseline insert",!
        quit
    }
    set t0 = $zh
    for i = 1:1:ROWS { set rs = stA.%Execute(i,"payload-"_i) }
    set elA = $zh - t0
    write "  ",ROWS," rows in ",$fnumber(elA,"",3),"s",!

    write !,"Q3.3 with outbox trigger -- ",ROWS," inserts",!
    set stB = ##class(%SQL.Statement).%New()
    set sc = stB.%Prepare("INSERT INTO SQLUser.SpikeQ3B (id,payload) VALUES (?,?)")
    if '$system.Status.IsOK(sc) {
        write "  prepare failed: ",$system.Status.GetErrorText(sc),!
        write !,"Q3 VERDICT: INCONCLUSIVE -- could not prepare trigger insert",!
        quit
    }
    set t0 = $zh
    for i = 1:1:ROWS { set rs = stB.%Execute(i,"payload-"_i) }
    set elB = $zh - t0
    write "  ",ROWS," rows in ",$fnumber(elB,"",3),"s",!

    write !,"Q3.4 verify the outbox captured the writes",!
    set captured = $get(^PGWireSync.Seq,0)
    write "  ^PGWireSync.Seq = ",captured," (expected ",ROWS,")",!
    if captured '= ROWS {
        write "  >> MISMATCH: trigger is not firing on every row",!
    }

    write !,"Q3.5 result",!
    set perA = (elA / ROWS) * 1000
    set perB = (elB / ROWS) * 1000
    set delta = perB - perA
    write "  baseline    : ",$fnumber(perA,"",4)," ms/row",!
    write "  with outbox : ",$fnumber(perB,"",4)," ms/row",!
    write "  delta       : ",$fnumber(delta,"",4)," ms/row",!
    write "  budget      : 5.0000 ms (constitutional)",!

    if captured '= ROWS {
        set verdict = "FAIL", note = "outbox captured "_captured_" of "_ROWS_" rows"
    } elseif delta < 0.5 {
        set verdict = "PASS", note = "trigger costs "_$fnumber(delta,"",4)_" ms/row, comfortably inside budget"
    } elseif delta < 5 {
        set verdict = "PASS", note = "trigger costs "_$fnumber(delta,"",4)_" ms/row, inside budget but material"
    } else {
        set verdict = "FAIL", note = "trigger costs "_$fnumber(delta,"",4)_" ms/row, at or over the 5 ms budget"
    }

    if %%KEEP%% = 0 {
        set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ3A")
        set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ3B")
        kill ^PGWireSync.Log, ^PGWireSync.Seq
        write !,"  (test tables and outbox globals removed)",!
    }
    write !,"Q3 VERDICT: ",verdict," -- ",note,!
    quit
}

}
