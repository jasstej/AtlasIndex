"use client";

import React, { useState, useEffect } from "react";

// API Endpoint configuration
const API_BASE = "http://127.0.0.1:8000";

interface ProjectItem {
  id: string;
  name: string;
  path: string;
  description: string | null;
  technologies: string[] | null;
  created_at: string;
  updated_at: string;
}

interface PortReservationItem {
  port: number;
  project_name: string;
  source: string;
  status: string;
  reserved_at: string;
}

interface DomainConfigItem {
  domain: string;
  project_name: string;
  proxy_type: string;
  ssl_status: boolean;
  config_path: string;
}

interface ServiceItem {
  name: string;
  type: string;
  status: string;
  description: string;
}

interface GraphLink {
  source: string;
  target: string;
  relation: string;
  port?: number;
}

interface SearchResultItem {
  type: string;
  name: string;
  project: string;
  file: string;
  line: number;
  snippet: string;
  score: number;
}

interface ToastNotification {
  message: string;
  type: string;
}

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [ports, setPorts] = useState<PortReservationItem[]>([]);
  const [domains, setDomains] = useState<DomainConfigItem[]>([]);
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([]);
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: GraphLink[] }>({ nodes: [], links: [] });
  const [mermaidGraph, setMermaidGraph] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [newProjectPath, setNewProjectPath] = useState<string>("");
  const [reserveProjectName, setReserveProjectName] = useState<string>("");
  const [reservePortNum, setReservePortNum] = useState<string>("");
  const [reservationResult, setReservationResult] = useState<any>(null);

  // Notifications
  const [notification, setNotification] = useState<ToastNotification | null>(null);

  // Fetch all basic stats and lists
  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [projRes, portRes, domRes, svcRes, graphRes, mermaidRes] = await Promise.all([
        fetch(`${API_BASE}/projects`).then((r) => r.json()),
        fetch(`${API_BASE}/ports`).then((r) => r.json()),
        fetch(`${API_BASE}/domains`).then((r) => r.json()),
        fetch(`${API_BASE}/services`).then((r) => r.json()),
        fetch(`${API_BASE}/dependencies`).then((r) => r.json()),
        fetch(`${API_BASE}/graph`).then((r) => r.json()),
      ]);

      setProjects(projRes);
      setPorts(portRes);
      setDomains(domRes);
      setServices(svcRes);
      setGraphData(graphRes);
      setMermaidGraph(mermaidRes.mermaid);
    } catch (e) {
      console.error(e);
      setError("Failed to fetch data from local API server. Please make sure the FastAPI backend is running on port 8000.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const showToast = (message: string, type: string = "success") => {
    setNotification({ message, type });
    setTimeout(() => setNotification(null), 4000);
  };

  // Add Project
  const handleAddProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectPath.trim()) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: newProjectPath }),
      });
      if (res.ok) {
        showToast("Project scan initiated in the background! Please reload in a few seconds.");
        setNewProjectPath("");
        setTimeout(fetchData, 3000);
      } else {
        const data = await res.json();
        showToast(data.detail || "Error registering project directory", "error");
      }
    } catch (err) {
      showToast("Network error trying to contact server", "error");
    } finally {
      setLoading(false);
    }
  };

  // Reserve Port
  const handleReservePort = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reserveProjectName.trim()) {
      showToast("Please enter or select a project name.", "error");
      return;
    }
    
    const payload: { project_name: string; port?: number } = { project_name: reserveProjectName };
    if (reservePortNum) {
      payload.port = parseInt(reservePortNum, 10);
    }

    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/ports/reserve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.ok) {
        setReservationResult(data);
        if (data.status === "success") {
          showToast(`Port reserved successfully: ${data.port}`);
          setReservePortNum("");
          fetchData();
        } else {
          showToast("Requested port conflicts with another service. See suggestions below.", "warning");
        }
      } else {
        showToast(data.detail || "Error booking port reservation", "error");
      }
    } catch (err) {
      showToast("Network error communicating with API.", "error");
    } finally {
      setLoading(false);
    }
  };

  // Run Semantic Code Search
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(searchQuery)}`);
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data);
        if (data.length === 0) {
          showToast("No code matches found. Try another query.", "warning");
        }
      } else {
        showToast("Search failed.", "error");
      }
    } catch (err) {
      showToast("Connection to API failed.", "error");
    } finally {
      setLoading(false);
    }
  };

  // Delete Project
  const handleDeleteProject = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to remove project '${name}' from AtlasIndex?`)) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/projects/${id}`, { method: "DELETE" });
      if (res.ok) {
        showToast(`Project '${name}' successfully removed.`);
        fetchData();
      } else {
        showToast("Failed to delete project.", "error");
      }
    } catch (err) {
      showToast("Network failure.", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-zinc-950 text-zinc-100 font-sans antialiased selection:bg-zinc-800 selection:text-white">
      {/* SIDEBAR */}
      <aside className="w-64 border-r border-zinc-800 bg-zinc-900/50 flex flex-col justify-between">
        <div>
          <div className="h-16 px-6 border-b border-zinc-800 flex items-center justify-between">
            <span className="font-bold tracking-tight text-white flex items-center gap-2">
              <span className="h-3.5 w-3.5 rounded bg-zinc-400 inline-block animate-pulse"></span>
              AtlasIndex
            </span>
            <span className="text-[10px] bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-400 font-mono">
              v1.0
            </span>
          </div>

          <nav className="p-4 space-y-1.5">
            {[
              { id: "overview", label: "Overview", icon: "📊" },
              { id: "projects", label: "Projects", icon: "📦" },
              { id: "ports", label: "Port Registry", icon: "🔌" },
              { id: "domains", label: "Domains Map", icon: "🌐" },
              { id: "search", label: "Semantic Search", icon: "🔍" },
              { id: "graph", label: "Dependencies Graph", icon: "🕸️" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id);
                  setError(null);
                }}
                className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                  activeTab === tab.id
                    ? "bg-zinc-800 text-white font-medium border-l-2 border-zinc-400 pl-2.5"
                    : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-200"
                }`}
              >
                <span>{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-4 border-t border-zinc-800 text-xs text-zinc-500 space-y-2">
          <div className="flex items-center justify-between">
            <span>Server Status</span>
            <span className="flex items-center gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${projects.length || ports.length ? "bg-green-500" : "bg-red-500 animate-ping"}`}></span>
              {projects.length || ports.length ? "Connected" : "Offline"}
            </span>
          </div>
          <button
            onClick={fetchData}
            className="w-full text-center py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded transition-colors"
          >
            Refresh Data
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT AREA */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* TOP HEADER */}
        <header className="h-16 border-b border-zinc-800 px-8 flex items-center justify-between bg-zinc-900/10">
          <h2 className="text-lg font-semibold text-white capitalize">
            {activeTab.replace("-", " ")}
          </h2>

          <div className="flex items-center gap-4">
            <span className="text-xs text-zinc-400 font-mono bg-zinc-900 px-2.5 py-1 rounded-full border border-zinc-800">
              Host: 127.0.0.1
            </span>
          </div>
        </header>

        {/* TOAST / NOTIFICATION */}
        {notification && (
          <div
            className={`mx-8 mt-4 p-3.5 rounded-lg text-sm border flex items-center justify-between transition-opacity duration-300 ${
              notification.type === "error"
                ? "bg-red-950/40 border-red-900 text-red-300"
                : notification.type === "warning"
                ? "bg-amber-950/40 border-amber-900 text-amber-300"
                : "bg-emerald-950/40 border-emerald-900 text-emerald-300"
            }`}
          >
            <span>{notification.message}</span>
            <button onClick={() => setNotification(null)} className="text-xs hover:text-white">✕</button>
          </div>
        )}

        {/* GLOBAL ERROR STATE */}
        {error && (
          <div className="m-8 p-6 bg-red-950/30 border border-red-900 rounded-xl text-red-200 text-sm space-y-4">
            <div className="font-bold flex items-center gap-2">⚠️ Server Disconnected</div>
            <p>{error}</p>
            <button
              onClick={fetchData}
              className="px-4 py-2 bg-red-900 hover:bg-red-800 text-white rounded transition-colors text-xs font-semibold"
            >
              Retry Connection
            </button>
          </div>
        )}

        {/* VIEWPORTS */}
        <main className="flex-1 p-8 overflow-y-auto min-w-0">
          {!error && (
            <>
              {/* TAB 1: OVERVIEW */}
              {activeTab === "overview" && (
                <div className="space-y-8 animate-fade-in">
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                    {[
                      { title: "Registered Projects", value: projects.length, icon: "📦" },
                      { title: "Managed Port Mappings", value: ports.length, icon: "🔌" },
                      { title: "Domains Configured", value: domains.length, icon: "🌐" },
                      { title: "Running Services", value: services.length, icon: "⚡" },
                    ].map((stat, idx) => (
                      <div key={idx} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 shadow-sm">
                        <div className="flex justify-between items-center text-zinc-500 text-xs font-semibold uppercase tracking-wider mb-2">
                          {stat.title}
                          <span className="text-lg">{stat.icon}</span>
                        </div>
                        <div className="text-3xl font-bold text-white">{stat.value}</div>
                      </div>
                    ))}
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    {/* Recent Projects Summary */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                      <h3 className="font-semibold text-white mb-4">Latest Discovered Projects</h3>
                      {projects.length === 0 ? (
                        <div className="text-zinc-500 text-sm">No projects scanned yet. Use the 'Projects' tab to add paths.</div>
                      ) : (
                        <div className="space-y-3">
                          {projects.slice(0, 5).map((p) => (
                            <div key={p.id} className="flex justify-between items-center p-3 bg-zinc-950 rounded border border-zinc-800/60">
                              <div>
                                <span className="font-medium text-white text-sm">{p.name}</span>
                                <div className="text-xs text-zinc-500 truncate max-w-sm">{p.path}</div>
                              </div>
                              <div className="flex gap-1.5">
                                {(p.technologies || []).map((t: string) => (
                                  <span key={t} className="text-[10px] bg-zinc-800 px-2 py-0.5 rounded text-zinc-400 capitalize">
                                    {t}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Active Services Summary */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                      <h3 className="font-semibold text-white mb-4">Active Server Services</h3>
                      {services.length === 0 ? (
                        <div className="text-zinc-500 text-sm">No running PM2/systemd/Docker/Supervisor processes detected.</div>
                      ) : (
                        <div className="space-y-3">
                          {services.slice(0, 5).map((s, idx) => (
                            <div key={idx} className="flex justify-between items-center p-3 bg-zinc-950 rounded border border-zinc-800/60">
                              <div>
                                <span className="font-medium text-white text-sm">{s.name}</span>
                                <div className="text-xs text-zinc-500 capitalize">{s.type} Service</div>
                              </div>
                              <span className="text-[11px] bg-emerald-950 border border-emerald-900 px-2.5 py-0.5 rounded text-emerald-400 font-semibold uppercase">
                                {s.status}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: PROJECTS */}
              {activeTab === "projects" && (
                <div className="space-y-6">
                  {/* Register Project Form */}
                  <form onSubmit={handleAddProject} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 flex flex-col md:flex-row gap-4 items-end">
                    <div className="flex-1 space-y-1.5 w-full">
                      <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Register Path</label>
                      <input
                        type="text"
                        placeholder="e.g. /home/server/projects/my-web-app"
                        value={newProjectPath}
                        onChange={(e) => setNewProjectPath(e.target.value)}
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3.5 py-2.5 text-zinc-200 focus:outline-none focus:border-zinc-500 text-sm"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={loading}
                      className="px-6 py-2.5 bg-zinc-100 text-zinc-900 rounded-lg hover:bg-zinc-200 transition-colors text-sm font-semibold w-full md:w-auto disabled:opacity-50"
                    >
                      Scan Directory
                    </button>
                  </form>

                  {/* Projects Table */}
                  <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="border-b border-zinc-800 bg-zinc-900/50 text-xs text-zinc-400 uppercase font-semibold">
                          <th className="p-4 pl-6">Project Name</th>
                          <th className="p-4">Technologies</th>
                          <th className="p-4">System Path</th>
                          <th className="p-4 text-right pr-6">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-800/60">
                        {projects.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="p-8 text-center text-zinc-500 text-sm">No registered projects scanned yet. Enter a path above to discover.</td>
                          </tr>
                        ) : (
                          projects.map((p) => (
                            <tr key={p.id} className="hover:bg-zinc-900/30 text-sm">
                              <td className="p-4 pl-6 font-semibold text-white">{p.name}</td>
                              <td className="p-4">
                                <div className="flex flex-wrap gap-1.5">
                                  {(p.technologies || []).map((t: string) => (
                                    <span key={t} className="text-[10px] bg-zinc-800/80 border border-zinc-800 px-2 py-0.5 rounded text-zinc-300 capitalize">
                                      {t}
                                    </span>
                                  ))}
                                </div>
                              </td>
                              <td className="p-4 font-mono text-xs text-zinc-400">{p.path}</td>
                              <td className="p-4 text-right pr-6">
                                <button
                                  onClick={() => handleDeleteProject(p.id, p.name)}
                                  className="text-xs text-red-400 hover:text-red-300 hover:underline"
                                >
                                  Deregister
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* TAB 3: PORTS REGISTRY */}
              {activeTab === "ports" && (
                <div className="space-y-6">
                  {/* Reserve Port Form */}
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <form onSubmit={handleReservePort} className="lg:col-span-1 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4 h-fit">
                      <h3 className="font-semibold text-white text-sm border-b border-zinc-800 pb-2">Reserve/Check Port Binding</h3>
                      
                      <div className="space-y-1.5">
                        <label className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">Project Name</label>
                        <select
                          value={reserveProjectName}
                          onChange={(e) => setReserveProjectName(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3.5 py-2.5 text-zinc-200 focus:outline-none focus:border-zinc-500 text-sm"
                        >
                          <option value="">-- Choose Discovered Project --</option>
                          {projects.map((p) => (
                            <option key={p.id} value={p.name}>{p.name}</option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">Target Port (Optional)</label>
                        <input
                          type="number"
                          placeholder="e.g. 3000 (leave blank for auto)"
                          value={reservePortNum}
                          onChange={(e) => setReservePortNum(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3.5 py-2.5 text-zinc-200 focus:outline-none focus:border-zinc-500 text-sm"
                        />
                      </div>

                      <button
                        type="submit"
                        disabled={loading}
                        className="w-full py-2.5 bg-zinc-100 text-zinc-900 rounded-lg hover:bg-zinc-200 transition-colors text-sm font-semibold disabled:opacity-50"
                      >
                        Reserve Port
                      </button>

                      {reservationResult && (
                        <div className="p-3 bg-zinc-950 rounded border border-zinc-800 text-xs text-zinc-400 space-y-2 mt-4">
                          {reservationResult.status === "success" ? (
                            <div className="text-emerald-400 font-semibold">✓ Port reserved successfully!</div>
                          ) : (
                            <div className="space-y-1.5">
                              <div className="text-amber-400 font-semibold">⚠️ Port conflict. Alternative options:</div>
                              <div className="flex gap-2 justify-center mt-1">
                                {reservationResult.suggested_alternatives?.map((p: number) => (
                                  <button
                                    key={p}
                                    type="button"
                                    onClick={() => setReservePortNum(String(p))}
                                    className="bg-zinc-800 hover:bg-zinc-700 text-white font-semibold py-1 px-3 rounded border border-zinc-700"
                                  >
                                    {p}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </form>

                    {/* Ports Table */}
                    <div className="lg:col-span-2 bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                      <table className="w-full text-left border-collapse">
                        <thead>
                          <tr className="border-b border-zinc-800 bg-zinc-900/50 text-xs text-zinc-400 uppercase font-semibold">
                            <th className="p-4 pl-6">Port</th>
                            <th className="p-4">Owner Project</th>
                            <th className="p-4">Source Mapped</th>
                            <th className="p-4">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/60">
                          {ports.length === 0 ? (
                            <tr>
                              <td colSpan={4} className="p-8 text-center text-zinc-500 text-sm">No port bindings registered. Reserve a port or run a scan.</td>
                            </tr>
                          ) : (
                            ports.map((p, idx) => (
                              <tr key={idx} className="hover:bg-zinc-900/30 text-sm">
                                <td className="p-4 pl-6 font-mono font-bold text-white">{p.port}</td>
                                <td className="p-4">{p.project_name}</td>
                                <td className="p-4 capitalize text-xs text-zinc-400 font-mono">{p.source}</td>
                                <td className="p-4">
                                  <span className={`text-[10px] px-2 py-0.5 rounded font-semibold uppercase ${
                                    p.status === "active"
                                      ? "bg-emerald-950/40 border border-emerald-900 text-emerald-400"
                                      : "bg-blue-950/40 border border-blue-900 text-blue-400"
                                  }`}>
                                    {p.status}
                                  </span>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 4: DOMAINS */}
              {activeTab === "domains" && (
                <div className="space-y-6">
                  {/* Domains Table */}
                  <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="border-b border-zinc-800 bg-zinc-900/50 text-xs text-zinc-400 uppercase font-semibold">
                          <th className="p-4 pl-6">Domain Address</th>
                          <th className="p-4">Target Project</th>
                          <th className="p-4">Reverse Proxy</th>
                          <th className="p-4">SSL Status</th>
                          <th className="p-4">Config Source</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-800/60">
                        {domains.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="p-8 text-center text-zinc-500 text-sm">No reverse proxy domains scanned. Scans read sites configured under Nginx sites-available/Caddyfile.</td>
                          </tr>
                        ) : (
                          domains.map((d, idx) => (
                            <tr key={idx} className="hover:bg-zinc-900/30 text-sm">
                              <td className="p-4 pl-6 font-semibold text-white hover:text-zinc-300">
                                <a href={`http://${d.domain}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5">
                                  {d.domain} ↗
                                </a>
                              </td>
                              <td className="p-4">{d.project_name}</td>
                              <td className="p-4 capitalize text-xs text-zinc-400 font-mono">{d.proxy_type}</td>
                              <td className="p-4">
                                <span className={`text-[10px] px-2 py-0.5 rounded font-semibold uppercase ${
                                  d.ssl_status
                                    ? "bg-emerald-950/40 border border-emerald-900 text-emerald-400"
                                    : "bg-amber-950/40 border border-amber-900 text-amber-400"
                                }`}>
                                  {d.ssl_status ? "SSL Secured" : "HTTP Only"}
                                </span>
                              </td>
                              <td className="p-4 font-mono text-[11px] text-zinc-500 truncate max-w-xs">{d.config_path}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* TAB 5: SEMANTIC SEARCH */}
              {activeTab === "search" && (
                <div className="space-y-6">
                  {/* Search Bar Form */}
                  <form onSubmit={handleSearch} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 flex gap-4">
                    <input
                      type="text"
                      placeholder="Search codebase structures... (e.g. 'jwt verification' or 'database connect')"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2.5 text-zinc-200 focus:outline-none focus:border-zinc-500 text-sm"
                    />
                    <button
                      type="submit"
                      disabled={loading}
                      className="px-6 py-2.5 bg-zinc-100 text-zinc-900 rounded-lg hover:bg-zinc-200 transition-colors text-sm font-semibold disabled:opacity-50"
                    >
                      Semantic Query
                    </button>
                  </form>

                  {/* Search Results Display */}
                  <div className="space-y-4">
                    {searchResults.length === 0 ? (
                      <div className="text-zinc-500 text-center py-12 bg-zinc-900/30 border border-zinc-800/60 rounded-xl text-sm">
                        Enter a coding query to seek out matched files, classes, methods, and functions.
                      </div>
                    ) : (
                      searchResults.map((r, idx) => (
                        <div key={idx} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-3">
                          <div className="flex justify-between items-start">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${
                                  r.type === "function" ? "bg-indigo-950 border border-indigo-900 text-indigo-400" : "bg-purple-950 border border-purple-900 text-purple-400"
                                }`}>
                                  {r.type}
                                </span>
                                <span className="font-semibold text-white text-base">{r.name}</span>
                              </div>
                              <div className="text-xs text-zinc-400 mt-1 font-mono">
                                Project: <span className="text-zinc-300 font-semibold">{r.project}</span> | Path: <span className="text-zinc-300">{r.file}:{r.line}</span>
                              </div>
                            </div>
                            {r.score !== 1.0 && (
                              <span className="text-[11px] bg-zinc-800 px-2 py-0.5 rounded text-zinc-300 font-mono">
                                Match Distance: {r.score.toFixed(3)}
                              </span>
                            )}
                          </div>
                          <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 overflow-x-auto">
                            <pre className="text-xs text-zinc-300 font-mono whitespace-pre-wrap">{r.snippet}</pre>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* TAB 6: DEPENDENCY GRAPH */}
              {activeTab === "graph" && (
                <div className="space-y-6">
                  {/* Graph Data Box */}
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Visual Edge Links List */}
                    <div className="lg:col-span-1 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
                      <h3 className="font-semibold text-white text-sm border-b border-zinc-800 pb-2">Dependency List</h3>
                      {graphData.links.length === 0 ? (
                        <div className="text-zinc-500 text-xs">No active links registered. Scans map internal imports and service port linkages.</div>
                      ) : (
                        <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                          {graphData.links.map((link, idx) => (
                            <div key={idx} className="p-2.5 bg-zinc-950 rounded border border-zinc-800/80 text-xs space-y-1.5">
                              <div className="flex justify-between items-center text-zinc-400">
                                <span className="truncate max-w-[100px] text-white font-semibold">{link.source.split(":").pop()}</span>
                                <span>⟶</span>
                                <span className="truncate max-w-[100px] text-white font-semibold">{link.target.split(":").pop()}</span>
                              </div>
                              <div className="flex justify-between text-[10px] text-zinc-500 font-mono">
                                <span className="capitalize">{link.relation}</span>
                                {link.port && <span>Port: {link.port}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Mermaid Markup Render Box */}
                    <div className="lg:col-span-2 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
                      <div className="flex justify-between items-center border-b border-zinc-800 pb-2">
                        <h3 className="font-semibold text-white text-sm">Mermaid Architecture Flowchart</h3>
                        <button
                          onClick={() => {
                            navigator.clipboard.writeText(mermaidGraph);
                            showToast("Mermaid markup copied to clipboard!");
                          }}
                          className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-200 px-2.5 py-1 rounded transition-colors"
                        >
                          Copy Diagram
                        </button>
                      </div>
                      <div className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 font-mono text-xs text-zinc-400 overflow-auto max-h-[400px] whitespace-pre">
                        {mermaidGraph || "No projects discovered to render diagrams."}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
