const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const { agentRequest } = require("./agent-api-helper");
const fs = require("fs");
let selectedWorkspace = null;


let processes = [];

ipcMain.handle("eva:select-folder", async (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return { canceled: true };

  const result = await dialog.showOpenDialog(win, {
    title: "Select EVA Agent Workspace",
    properties: ["openDirectory", "createDirectory"]
  });

  if (result.canceled || !result.filePaths.length) {
    return { canceled: true };
  }

  selectedWorkspace = path.resolve(result.filePaths[0]);
  return { canceled: false, path: selectedWorkspace };
});

ipcMain.handle("eva:agent-run", async (_event, payload) => {
  const task = typeof payload?.task === "string" ? payload.task.trim() : "";
  const workspace = typeof payload?.workspace === "string"
    ? path.resolve(payload.workspace)
    : "";

  if (!task) throw new Error("Enter an Agent task first.");
  if (!selectedWorkspace || workspace !== selectedWorkspace) {
    throw new Error("Select the workspace folder again before running the Agent.");
  }
  if (!fs.existsSync(workspace) || !fs.statSync(workspace).isDirectory()) {
    throw new Error("Selected workspace folder does not exist.");
  }

  return agentRequest("/agent/run", "POST", { task, workspace });
});

ipcMain.handle("eva:agent-status", async (_event, payload) => {
  const jobId = String(payload?.jobId || "");
  if (!/^[a-f0-9]{8}$/i.test(jobId)) throw new Error("Invalid Agent job ID.");
  return agentRequest("/agent/status/" + jobId);
});

ipcMain.handle("eva:agent-approve", async (_event, payload) => {
  const jobId = String(payload?.jobId || "");
  if (!/^[a-f0-9]{8}$/i.test(jobId)) throw new Error("Invalid Agent job ID.");
  if (typeof payload?.ok !== "boolean") throw new Error("Approval must be true or false.");
  return agentRequest("/agent/approve/" + jobId + "?ok=" + payload.ok, "POST");
});
function startProcess(command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    shell: false,
    windowsHide: true
  });

  processes.push(child);

  child.on("error", (err) => {
    console.error(`Process error: ${err.message}`);
  });

  return child;
}

function startServices() {
  const root = "D:\\Eva_Ai_brain";
  startProcess(
    path.join(root, ".openhands-venv", "Scripts", "python.exe"),
    ["-m", "uvicorn", "src.agent_service:app", "--host", "127.0.0.1", "--port", "8100"],
    root
  );


  startProcess(
    path.join(root, ".venv", "Scripts", "python.exe"),
    ["-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "3000"],
    root
  );

  startProcess(
    path.join(root, ".venv", "Scripts", "python.exe"),
    ["-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"],
    root
  );

  startProcess(
    path.join(root, "eva-ml-service", ".venv", "Scripts", "python.exe"),
    ["app.py"],
    path.join(root, "eva-ml-service")
  );
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  console.log("DIR:", __dirname);
  console.log("INDEX:", path.join(__dirname, "build", "index.html"));
  console.log("EXISTS:", require("fs").existsSync(path.join(__dirname, "build", "index.html")));
  win.webContents.on("will-navigate", (event, url) => {
    console.log("[EVA NAVIGATION]", url);

    if (url.startsWith("file:///D:/") && !url.includes("index.html")) {
      console.trace("[EVA BLOCKED FILE NAVIGATION]");
      event.preventDefault();
    }
  });

  win.webContents.on("did-fail-load", (_event, code, description, url) => {
  console.error("[EVA LOAD FAILED]", { code, description, url });
  });
  win.loadFile(path.join(__dirname, "build", "index.html"));
  win.webContents.openDevTools();
}

app.whenReady().then(() => {
  startServices();

  setTimeout(createWindow, 5000);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  processes.forEach((child) => {
    try {
      child.kill();
    } catch {}
  });
});




