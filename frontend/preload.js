const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("evaDesktop", {
  isDesktop: true,
  selectFolder: () => ipcRenderer.invoke("eva:select-folder"),
  runAgent: (task, workspace) =>
    ipcRenderer.invoke("eva:agent-run", { task, workspace }),
  getAgentStatus: (jobId) =>
    ipcRenderer.invoke("eva:agent-status", { jobId }),
  approveAgent: (jobId, ok) =>
    ipcRenderer.invoke("eva:agent-approve", { jobId, ok })
});
