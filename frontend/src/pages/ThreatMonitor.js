import React, { useEffect, useState } from "react";

const ThreatMonitor = () => {
  const [threats, setThreats] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadThreats = async () => {
    try {
      const res = await fetch("/api/security/threats");
      const json = await res.json();

      setThreats(json.threats || []);
    } catch (err) {
      console.error("Threat monitor load failed:", err);
      setThreats([]);
    }

    setLoading(false);
  };

  useEffect(() => {
    loadThreats();

    const interval = setInterval(() => {
      loadThreats();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Threat Monitor</h1>
          <p style={styles.subtitle}>
            Live AI firewall threat detection and blocked request monitoring
          </p>
        </div>

        <button onClick={loadThreats} style={styles.refreshBtn}>
          Refresh
        </button>
      </div>

      <div style={styles.cards}>
        <MetricCard title="Total Threats" value={threats.length} />
        <MetricCard
          title="Blocked"
          value={threats.filter((t) => t.blocked).length}
        />
        <MetricCard
          title="High/Critical"
          value={
            threats.filter(
              (t) => t.severity === "HIGH" || t.severity === "CRITICAL"
            ).length
          }
        />
      </div>

      <section style={styles.panel}>
        <h2>Threat Events</h2>

        {loading ? (
          <p style={styles.empty}>Loading threats...</p>
        ) : threats.length === 0 ? (
          <p style={styles.empty}>No threats detected yet</p>
        ) : (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>ID</th>
                  <th style={styles.th}>Threat Type</th>
                  <th style={styles.th}>Severity</th>
                  <th style={styles.th}>Source IP</th>
                  <th style={styles.th}>Blocked</th>
                  <th style={styles.th}>Detected Data</th>
                  <th style={styles.th}>Created At</th>
                </tr>
              </thead>

              <tbody>
                {threats.map((threat) => (
                  <tr key={threat.id}>
                    <td style={styles.td}>{threat.id}</td>
                    <td style={styles.td}>{threat.threat_type}</td>
                    <td style={styles.td}>
                      <span style={getSeverityStyle(threat.severity)}>
                        {threat.severity}
                      </span>
                    </td>
                    <td style={styles.td}>{threat.source_ip}</td>
                    <td style={styles.td}>
                      {threat.blocked ? "YES" : "NO"}
                    </td>
                    <td style={styles.td}>
                      {getDetectedData(threat)}
                    </td>
                    <td style={styles.td}>{threat.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};

const MetricCard = ({ title, value }) => (
  <div style={styles.card}>
    <p style={styles.cardTitle}>{title}</p>
    <h2 style={styles.cardValue}>{value}</h2>
  </div>
);

const getDetectedData = (threat) => {
  const data = threat.data || {};

  if (data.detected_items) {
    return data.detected_items
      .map((item) => `${item.type}: ${item.matches.join(", ")}`)
      .join(" | ");
  }

  if (data.detected_patterns) {
    return data.detected_patterns.join(", ");
  }

  if (data.prompt) {
    return data.prompt;
  }

  return "Security event";
};

const getSeverityStyle = (severity) => {
  const base = {
    padding: "5px 10px",
    borderRadius: "999px",
    fontSize: "12px",
    fontWeight: 700
  };

  if (severity === "CRITICAL") {
    return {
      ...base,
      background: "#7f1d1d",
      color: "#fecaca"
    };
  }

  if (severity === "HIGH") {
    return {
      ...base,
      background: "#991b1b",
      color: "#fee2e2"
    };
  }

  if (severity === "MEDIUM") {
    return {
      ...base,
      background: "#78350f",
      color: "#fde68a"
    };
  }

  return {
    ...base,
    background: "#14532d",
    color: "#bbf7d0"
  };
};

const styles = {
  page: {
    minHeight: "100vh",
    padding: "28px",
    background: "#020617",
    color: "#e5e7eb"
  },

  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "24px"
  },

  title: {
    fontSize: "34px",
    margin: 0
  },

  subtitle: {
    color: "#93c5fd",
    marginTop: "6px"
  },

  refreshBtn: {
    background: "#2563eb",
    color: "#fff",
    border: "none",
    padding: "12px 18px",
    borderRadius: "10px",
    cursor: "pointer",
    fontWeight: 700
  },

  cards: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "18px",
    marginBottom: "24px"
  },

  card: {
    background: "#111827",
    border: "1px solid #1e293b",
    borderRadius: "16px",
    padding: "20px"
  },

  cardTitle: {
    color: "#93c5fd",
    margin: 0
  },

  cardValue: {
    fontSize: "32px",
    margin: "10px 0 0"
  },

  panel: {
    background: "#111827",
    border: "1px solid #1e293b",
    borderRadius: "18px",
    padding: "22px"
  },

  tableWrap: {
    overflowX: "auto"
  },

  table: {
    width: "100%",
    borderCollapse: "collapse"
  },

  th: {
    textAlign: "left",
    padding: "14px",
    color: "#93c5fd",
    borderBottom: "1px solid #334155"
  },

  td: {
    padding: "14px",
    borderBottom: "1px solid #1e293b",
    color: "#e5e7eb",
    verticalAlign: "top"
  },

  empty: {
    color: "#64748b"
  }
};

export default ThreatMonitor;