"""
╔══════════════════════════════════════════════════════════╗
║         SQL SERVER BACKUP TOOL — SBP_RGTRABAJO           ║
║  Genera TXT con SELECT * FROM tabla (millones de filas)  ║
╚══════════════════════════════════════════════════════════╝

REQUISITOS:
    pip install pyodbc

CONFIGURACIÓN (editar las variables en la sección CONFIG):
    - SERVER      : Nombre o IP del servidor SQL Server
    - DATABASE    : Nombre de la base de datos
    - OUTPUT_DIR  : Carpeta donde se guardarán los .txt generados

TABLAS CONFIGURADAS:
    - SBP_RGTRABAJO.dbo.LVND10
    - SBP_RGTRABAJO.dbo.fsd_601
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyodbc
import threading
import os
import time
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# ███  CONFIGURACIÓN — EDITAR AQUÍ  ███
# ─────────────────────────────────────────────────────────────────────────────

SERVER      = "TU_SERVIDOR_AQUI"          # Ej: "192.168.1.10" o "MISERVER\SQLEXPRESS"
DATABASE    = "TU_BASE_DE_DATOS_AQUI"     # Ej: "SBP_RGTRABAJO"
OUTPUT_DIR  = r"C:\RUTA\DONDE\GUARDAR"   # Ej: r"D:\Backups\SQL"

# Driver ODBC instalado en el equipo (ajustar si es necesario)
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

# Filas por lote al leer (afecta uso de memoria y velocidad)
# Para 40M registros se recomienda entre 5000 y 20000
CHUNK_SIZE  = 10_000

# Separador de columnas en el TXT de salida
SEPARATOR   = "|"

# Tablas disponibles para backup
TABLES = [
    "SBP_RGTRABAJO.dbo.LVND10",
    "SBP_RGTRABAJO.dbo.fsd_601",
    "SBP_RGTRABAJO.dbo.fsd601",
    "SBP_RGTRABAJO.dbo.fsd602",
    "SBP_RGTRABAJO.dbo.fsd602_base",
]

# ─────────────────────────────────────────────────────────────────────────────


def build_connection_string() -> str:
    return (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        "Trusted_Connection=yes;"          # Windows Auth
        # Si usas SQL Auth descomenta las dos líneas siguientes y comenta la de arriba:
        # f"UID=TU_USUARIO;"
        # f"PWD=TU_PASSWORD;"
    )


def format_time(seconds: float) -> str:
    """Convierte segundos a string HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def run_backup(table_name: str, app: "BackupApp"):
    """
    Ejecuta el backup en un hilo separado para no bloquear la GUI.
    Lee por chunks y escribe incrementalmente al disco.
    """
    app.set_state("running")
    app.log(f"▶  Iniciando backup de: {table_name}")
    app.log(f"   Servidor  : {SERVER}")
    app.log(f"   Base datos: {DATABASE}")

    # Preparar nombre de archivo de salida
    safe_name = table_name.replace(".", "_").replace(" ", "_")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename   = f"backup_{safe_name}_{timestamp}.txt"
    filepath   = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    app.log(f"   Archivo   : {filepath}")
    app.log("─" * 60)

    try:
        conn_str = build_connection_string()
        app.log("🔌 Conectando al servidor...")
        conn   = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # ── Contar filas para barra de progreso ──────────────────────────────
        app.log("🔍 Contando registros (puede tardar unos segundos)...")
        count_q = f"SELECT COUNT(*) FROM {table_name}"
        cursor.execute(count_q)
        total_rows = cursor.fetchone()[0]
        app.log(f"   Total de filas: {total_rows:,}")
        app.set_total(total_rows)

        # ── Ejecutar SELECT * ────────────────────────────────────────────────
        app.log(f"📋 Ejecutando SELECT * FROM {table_name}...")
        cursor.execute(f"SELECT * FROM {table_name}")

        # Obtener nombres de columnas para la cabecera
        columns = [desc[0] for desc in cursor.description]

        rows_written = 0
        start_time   = time.time()
        last_log     = time.time()

        with open(filepath, "w", encoding="utf-8", buffering=1024 * 1024) as f:
            # Cabecera
            f.write(SEPARATOR.join(columns) + "\n")

            # ── Lectura en chunks ────────────────────────────────────────────
            while True:
                rows = cursor.fetchmany(CHUNK_SIZE)
                if not rows:
                    break

                # Escribir cada fila al archivo
                for row in rows:
                    line = SEPARATOR.join(
                        "" if v is None else str(v).replace("\n", " ").replace("\r", " ")
                        for v in row
                    )
                    f.write(line + "\n")

                rows_written += len(rows)
                elapsed = time.time() - start_time

                # Velocidad y ETA
                speed = rows_written / elapsed if elapsed > 0 else 0
                remaining = (total_rows - rows_written) / speed if speed > 0 else 0

                app.set_progress(rows_written)
                app.update_stats(rows_written, total_rows, elapsed, speed, remaining)

                # Log periódico cada 30 segundos
                if time.time() - last_log >= 30:
                    pct = (rows_written / total_rows * 100) if total_rows else 0
                    app.log(
                        f"   ⏳ {rows_written:,} / {total_rows:,} filas  "
                        f"({pct:.1f}%)  |  ETA: {format_time(remaining)}"
                    )
                    last_log = time.time()

        elapsed_total = time.time() - start_time
        size_mb = os.path.getsize(filepath) / (1024 * 1024)

        app.log("─" * 60)
        app.log(f"✅ Backup completado exitosamente.")
        app.log(f"   Filas escritas : {rows_written:,}")
        app.log(f"   Tiempo total   : {format_time(elapsed_total)}")
        app.log(f"   Tamaño archivo : {size_mb:.2f} MB")
        app.log(f"   Guardado en    : {filepath}")

        cursor.close()
        conn.close()
        app.set_state("done", success=True)

    except pyodbc.Error as db_err:
        app.log(f"❌ Error de base de datos: {db_err}")
        app.set_state("done", success=False)
    except Exception as e:
        app.log(f"❌ Error inesperado: {e}")
        app.set_state("done", success=False)


# ─────────────────────────────────────────────────────────────────────────────
#  INTERFAZ GRÁFICA
# ─────────────────────────────────────────────────────────────────────────────

class BackupApp:
    BG        = "#0d1117"
    CARD      = "#161b22"
    BORDER    = "#30363d"
    ACCENT    = "#2ea44f"
    ACCENT2   = "#58a6ff"
    RED       = "#f85149"
    TEXT      = "#e6edf3"
    MUTED     = "#8b949e"
    FONT_MAIN = ("Consolas", 10)
    FONT_HDR  = ("Consolas", 13, "bold")
    FONT_BTN  = ("Consolas", 11, "bold")
    FONT_MONO = ("Consolas", 9)

    def __init__(self, root: tk.Tk):
        self.root  = root
        self._total_rows = 1
        self._running    = False

        root.title("SQL Server Backup Tool — SBP_RGTRABAJO")
        root.configure(bg=self.BG)
        root.resizable(True, True)
        root.minsize(780, 620)

        self._build_ui()
        self.log("🛠  SQL Server Backup Tool listo.")
        self.log(f"   Servidor configurado : {SERVER}")
        self.log(f"   Base de datos        : {DATABASE}")
        self.log(f"   Directorio de salida : {OUTPUT_DIR}")
        self.log("─" * 60)
        self.log("Presiona un botón de tabla para iniciar el backup.")

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Título ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=self.BG)
        hdr.pack(fill="x", padx=20, pady=(18, 0))

        tk.Label(
            hdr, text="◈  SQL BACKUP TOOL",
            font=("Consolas", 16, "bold"),
            bg=self.BG, fg=self.ACCENT2
        ).pack(side="left")

        self._lbl_status = tk.Label(
            hdr, text="● IDLE",
            font=("Consolas", 10, "bold"),
            bg=self.BG, fg=self.MUTED
        )
        self._lbl_status.pack(side="right", padx=4)

        tk.Label(
            hdr, text=f"  {SERVER}  /  {DATABASE}",
            font=self.FONT_MONO, bg=self.BG, fg=self.MUTED
        ).pack(side="right")

        ttk.Separator(self.root, orient="horizontal").pack(
            fill="x", padx=20, pady=10
        )

        # ── Botones de tabla ──────────────────────────────────────────────────
        btn_frame = tk.Frame(self.root, bg=self.BG)
        btn_frame.pack(fill="x", padx=20, pady=(0, 10))

        tk.Label(
            btn_frame, text="SELECCIONAR TABLA",
            font=("Consolas", 9), bg=self.BG, fg=self.MUTED
        ).pack(anchor="w", pady=(0, 6))

        # Sub-frame exclusivo para grid (evita conflicto con pack del label)
        grid_frame = tk.Frame(btn_frame, bg=self.BG)
        grid_frame.pack(anchor="w")

        self._table_buttons = []
        COLS = 3  # botones por fila
        for i, tbl in enumerate(TABLES):
            btn = tk.Button(
                grid_frame,
                text=f"  ⬇  {tbl}  ",
                font=self.FONT_BTN,
                bg=self.CARD, fg=self.TEXT,
                activebackground=self.ACCENT, activeforeground="#ffffff",
                relief="flat", bd=0, cursor="hand2",
                padx=14, pady=10,
                highlightthickness=1,
                highlightbackground=self.BORDER,
                command=lambda t=tbl: self._on_backup_click(t)
            )
            row, col = divmod(i, COLS)
            btn.grid(row=row, column=col, padx=(0, 10), pady=(0, 8), sticky="w")
            self._table_buttons.append(btn)

        # ── Barra de progreso ─────────────────────────────────────────────────
        prog_card = tk.Frame(self.root, bg=self.CARD, bd=0)
        prog_card.pack(fill="x", padx=20, pady=(4, 0))

        tk.Label(
            prog_card, text="PROGRESO",
            font=("Consolas", 8), bg=self.CARD, fg=self.MUTED
        ).pack(anchor="w", padx=12, pady=(10, 2))

        self._progressvar = tk.DoubleVar(value=0)
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor=self.BG,
            background=self.ACCENT,
            thickness=14
        )
        self._progressbar = ttk.Progressbar(
            prog_card, variable=self._progressvar,
            maximum=100, length=740,
            style="Green.Horizontal.TProgressbar"
        )
        self._progressbar.pack(fill="x", padx=12, pady=(0, 6))

        # Estadísticas en línea
        stats_row = tk.Frame(prog_card, bg=self.CARD)
        stats_row.pack(fill="x", padx=12, pady=(0, 10))

        self._lbl_rows     = self._stat_label(stats_row, "FILAS",    "0 / 0")
        self._lbl_pct      = self._stat_label(stats_row, "%",        "0.00 %")
        self._lbl_speed    = self._stat_label(stats_row, "VELOCIDAD","0 filas/s")
        self._lbl_elapsed  = self._stat_label(stats_row, "ELAPSED",  "00:00:00")
        self._lbl_eta      = self._stat_label(stats_row, "ETA",      "—")

        # ── Log de eventos ────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=self.BG)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(12, 14))

        tk.Label(
            log_frame, text="LOG DE EVENTOS",
            font=("Consolas", 8), bg=self.BG, fg=self.MUTED
        ).pack(anchor="w", pady=(0, 4))

        text_container = tk.Frame(log_frame, bg=self.BORDER, bd=1)
        text_container.pack(fill="both", expand=True)

        self._log_text = tk.Text(
            text_container,
            font=self.FONT_MONO,
            bg="#010409", fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            padx=10, pady=8
        )
        self._log_text.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(text_container, command=self._log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self._log_text["yscrollcommand"] = scrollbar.set

        # Configurar colores de tags del log
        self._log_text.tag_configure("green",  foreground=self.ACCENT)
        self._log_text.tag_configure("blue",   foreground=self.ACCENT2)
        self._log_text.tag_configure("red",    foreground=self.RED)
        self._log_text.tag_configure("muted",  foreground=self.MUTED)

        # ── Barra inferior ────────────────────────────────────────────────────
        bottom = tk.Frame(self.root, bg=self.CARD)
        bottom.pack(fill="x", padx=0, pady=0, side="bottom")

        tk.Button(
            bottom, text="📂  Cambiar directorio de salida",
            font=self.FONT_MONO, bg=self.CARD, fg=self.MUTED,
            relief="flat", bd=0, cursor="hand2", padx=10, pady=6,
            command=self._change_output_dir
        ).pack(side="left", padx=10)

        tk.Button(
            bottom, text="🗑  Limpiar log",
            font=self.FONT_MONO, bg=self.CARD, fg=self.MUTED,
            relief="flat", bd=0, cursor="hand2", padx=10, pady=6,
            command=self._clear_log
        ).pack(side="left")

        self._lbl_outdir = tk.Label(
            bottom, text=f"OUT → {OUTPUT_DIR}",
            font=self.FONT_MONO, bg=self.CARD, fg=self.MUTED
        )
        self._lbl_outdir.pack(side="right", padx=14, pady=6)

    def _stat_label(self, parent, title: str, value: str):
        frame = tk.Frame(parent, bg=self.CARD)
        frame.pack(side="left", padx=(0, 24))
        tk.Label(frame, text=title, font=("Consolas", 7),
                 bg=self.CARD, fg=self.MUTED).pack(anchor="w")
        lbl = tk.Label(frame, text=value, font=("Consolas", 10, "bold"),
                       bg=self.CARD, fg=self.TEXT)
        lbl.pack(anchor="w")
        return lbl

    # ── Métodos de control ────────────────────────────────────────────────────

    def _on_backup_click(self, table_name: str):
        if self._running:
            messagebox.showwarning(
                "Backup en progreso",
                "Ya hay un backup en curso. Espera a que termine."
            )
            return

        answer = messagebox.askyesno(
            "Confirmar backup",
            f"¿Iniciar backup de:\n\n{table_name}\n\nEsto puede tardar varios minutos."
        )
        if not answer:
            return

        thread = threading.Thread(
            target=run_backup,
            args=(table_name, self),
            daemon=True
        )
        thread.start()

    def _change_output_dir(self):
        global OUTPUT_DIR
        new_dir = filedialog.askdirectory(title="Seleccionar directorio de salida")
        if new_dir:
            OUTPUT_DIR = new_dir
            self._lbl_outdir.config(text=f"OUT → {OUTPUT_DIR}")
            self.log(f"📂 Directorio de salida cambiado a: {OUTPUT_DIR}")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── Métodos llamados desde el hilo de backup ──────────────────────────────

    def log(self, message: str):
        """Agrega una línea al log (thread-safe)."""
        def _insert():
            self._log_text.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")

            tag = "muted"
            if "✅" in message or "▶" in message:
                tag = "green"
            elif "❌" in message:
                tag = "red"
            elif "🔌" in message or "📋" in message or "📂" in message:
                tag = "blue"

            self._log_text.insert("end", f"[{ts}] {message}\n", tag)
            self._log_text.see("end")
            self._log_text.config(state="disabled")

        self.root.after(0, _insert)

    def set_total(self, total: int):
        self._total_rows = total if total > 0 else 1
        self.root.after(0, lambda: self._lbl_rows.config(
            text=f"0 / {total:,}"
        ))

    def set_progress(self, rows_done: int):
        pct = (rows_done / self._total_rows) * 100
        self.root.after(0, lambda: self._progressvar.set(pct))

    def update_stats(self, rows: int, total: int, elapsed: float,
                     speed: float, remaining: float):
        pct = (rows / total * 100) if total else 0

        def _update():
            self._lbl_rows.config(text=f"{rows:,} / {total:,}")
            self._lbl_pct.config(text=f"{pct:.2f} %")
            self._lbl_speed.config(text=f"{speed:,.0f} filas/s")
            self._lbl_elapsed.config(text=format_time(elapsed))
            self._lbl_eta.config(text=format_time(remaining))

        self.root.after(0, _update)

    def set_state(self, state: str, success: bool = True):
        def _update():
            if state == "running":
                self._running = True
                self._lbl_status.config(text="● RUNNING", fg="#f0a500")
                for b in self._table_buttons:
                    b.config(state="disabled", fg=self.MUTED)

            elif state == "done":
                self._running = False
                if success:
                    self._lbl_status.config(text="● DONE", fg=self.ACCENT)
                    self._progressvar.set(100)
                else:
                    self._lbl_status.config(text="● ERROR", fg=self.RED)
                for b in self._table_buttons:
                    b.config(state="normal", fg=self.TEXT)

        self.root.after(0, _update)


# ─────────────────────────────────────────────────────────────────────────────
#  PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app  = BackupApp(root)
    root.mainloop()
