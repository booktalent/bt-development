/**
 * ManagerLeaderboard — public within the manager team.
 *
 * A manager sees the full team ranked by revenue this month, with their
 * own row highlighted. Admin can see the same view too. Uses the
 * `/manager/leaderboard` endpoint from Iter 89.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Nav from "../../components/Nav";
import api, { fmtINRFull, formatApiError as fmt } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useToast } from "../../lib/toast";


export default function ManagerLeaderboard() {
  const { user } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));

  const load = async () => {
    try {
      const r = await api.get(`/manager/leaderboard?month=${month}`);
      setData(r.data);
    } catch (e) { toast(fmt(e), "error"); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [month]);

  return (
    <div>
      <Nav />
      <div className="pad-24" data-testid="manager-leaderboard" style={{ maxWidth: 960, margin: "0 auto" }}>
        <div className="flex-between mb-16" style={{ flexWrap: "wrap", gap: 12 }}>
          <div>
            <div className="text-muted fs-12" style={{ letterSpacing: ".14em", textTransform: "uppercase" }}>
              Team Leaderboard
            </div>
            <h1 className="font-serif fs-28 fw-700 text-gold" data-testid="lb-title">
              {data?.month ? `Rankings · ${data.month}` : "Rankings"}
            </h1>
            {data?.my_rank && (
              <div className="text-muted fs-13 mt-4" data-testid="lb-my-rank">
                You're ranked <b className="text-gold">#{data.my_rank}</b> out of {data.count}
              </div>
            )}
          </div>
          <div className="flex gap-8" style={{ alignItems: "center" }}>
            <input className="input" type="month" value={month}
              onChange={(e) => setMonth(e.target.value)}
              data-testid="lb-month" style={{ width: 180 }} />
            <Link to={user?.role === "admin" ? "/admin" : "/manager"} className="btn btn-ghost btn-sm">
              ← Back
            </Link>
          </div>
        </div>

        {!data && <div className="text-muted">Loading…</div>}
        {data && data.items.length === 0 && (
          <div className="card card-pad text-center text-muted" data-testid="lb-empty">
            No managers on the team yet.
          </div>
        )}

        {/* Podium — top 3 */}
        {data && data.items.length > 0 && (
          <>
            <div className="grid grid-3 gap-16 mb-16" data-testid="lb-podium">
              {data.items.slice(0, 3).map((m) => (
                <div key={m.manager_id}
                     className="card card-pad"
                     data-testid={`lb-podium-${m.rank}`}
                     style={{
                       border: m.is_me ? "1.5px solid #D4AF37" : "1px solid rgba(255,255,255,0.06)",
                       background: m.rank === 1
                         ? "linear-gradient(135deg, rgba(212,175,55,0.15), rgba(212,175,55,0.03))"
                         : "rgba(255,255,255,0.03)",
                     }}>
                  <div className="flex-between mb-8">
                    <div style={{ fontSize: 28 }}>{m.rank_medal}</div>
                    <div className="font-serif fs-28 fw-700 text-gold">#{m.rank}</div>
                  </div>
                  <div className="fw-700 fs-18">{m.manager_name}</div>
                  {m.is_me && <span className="pill pill-gold" style={{ fontSize: 10 }}>YOU</span>}
                  <div className="mt-8">
                    <div className="text-muted fs-11">Revenue</div>
                    <div className="text-gold font-serif fs-22 fw-700">{fmtINRFull(m.revenue)}</div>
                  </div>
                  <div className="mt-8 flex gap-16 fs-12">
                    <div><span className="text-muted">Won:</span> <b className="text-green">{m.leads_won}</b></div>
                    <div><span className="text-muted">Conv:</span> <b>{m.conversion_pct}%</b></div>
                  </div>
                </div>
              ))}
            </div>

            {/* Rest of the table */}
            <div className="card">
              <table className="table" data-testid="lb-table">
                <thead>
                  <tr>
                    <th style={{ width: 60 }}>Rank</th>
                    <th>Manager</th>
                    <th>Revenue</th>
                    <th>Won</th>
                    <th>Lost</th>
                    <th>Conversion</th>
                    <th>Target Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((m) => {
                    const revPct = m.monthly_revenue_target > 0
                      ? Math.round((m.revenue / m.monthly_revenue_target) * 100)
                      : null;
                    return (
                      <tr key={m.manager_id}
                          data-testid={`lb-row-${m.manager_id}`}
                          style={m.is_me ? { background: "rgba(212,175,55,0.06)" } : {}}>
                        <td className="fw-700">
                          {m.rank_medal || `#${m.rank}`}
                        </td>
                        <td>
                          <div className="fw-700">{m.manager_name}</div>
                          {m.is_me && <span className="pill pill-gold" style={{ fontSize: 10 }}>YOU</span>}
                        </td>
                        <td className="text-gold font-serif fw-700">{fmtINRFull(m.revenue)}</td>
                        <td className="text-green">{m.leads_won}</td>
                        <td className="text-red">{m.leads_lost}</td>
                        <td>{m.conversion_pct}%</td>
                        <td>
                          {revPct === null
                            ? <span className="text-muted fs-12">no target</span>
                            : <>
                                <div className="fs-12">{revPct}%</div>
                                <div style={{ height: 4, background: "rgba(255,255,255,0.08)", borderRadius: 2 }}>
                                  <div style={{
                                    width: `${Math.min(100, revPct)}%`, height: "100%",
                                    background: revPct >= 100 ? "#6ee7a8" : "#D4AF37",
                                    borderRadius: 2,
                                  }} />
                                </div>
                              </>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
