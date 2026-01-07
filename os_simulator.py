#!/usr/bin/env python3

import sys
import random
import threading
import time
from typing import List, Tuple, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QTextEdit,
    QSpinBox, QGroupBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex, QWaitCondition
from PyQt6.QtGui import QFont, QColor


class Process:
    
    def __init__(self, pid: int, max_demand: List[int]):
        self.pid = pid
        self.max_demand = max_demand
        self.allocation = [0] * len(max_demand)
        self.need = max_demand.copy()
        self.status = "Waiting"
        self.lock = threading.Lock()
        
    def update_need(self):
        self.need = [self.max_demand[i] - self.allocation[i] 
                    for i in range(len(self.max_demand))]
    
    def _is_finished(self) -> bool:
        return all(need == 0 for need in self.need)
    
    def is_finished(self) -> bool:
        with self.lock:
            return self._is_finished()
    
    def get_status(self) -> str:
        with self.lock:
            return self.status
    
    def set_status(self, status: str):
        with self.lock:
            self.status = status


class BankerAlgorithm:
    
    def __init__(self, num_processes: int, num_resources: int, 
                 available: List[int], processes: List[Process]):
        self.num_processes = num_processes
        self.num_resources = num_resources
        self.available = available.copy()
        self.processes = processes
        self.lock = threading.Lock()
        
    def _is_safe_state(self) -> Tuple[bool, List[int]]:
        work = self.available.copy()
        finish = [False] * self.num_processes
        safe_sequence = []
        
        found = True
        while found:
            found = False
            for i in range(self.num_processes):
                if not finish[i]:
                    with self.processes[i].lock:
                        can_allocate = all(
                            self.processes[i].need[j] <= work[j]
                            for j in range(self.num_resources)
                        )
                    
                    if can_allocate:
                        with self.processes[i].lock:
                            for j in range(self.num_resources):
                                work[j] += self.processes[i].allocation[j]
                        finish[i] = True
                        safe_sequence.append(i)
                        found = True
                        break
        
        is_safe = all(finish)
        return is_safe, safe_sequence
    
    def is_safe_state(self) -> Tuple[bool, List[int]]:
        with self.lock:
            return self._is_safe_state()
    
    def request_resources(self, process_id: int, request: List[int]) -> Tuple[bool, str]:
        with self.lock:
            process = self.processes[process_id]
            
            with process.lock:
                if any(request[i] > process.need[i] for i in range(self.num_resources)):
                    return False, f"Process {process_id}: Request exceeds need"
            
            if any(request[i] > self.available[i] for i in range(self.num_resources)):
                return False, f"Process {process_id}: Insufficient resources available"
            
            for i in range(self.num_resources):
                self.available[i] -= request[i]
                with process.lock:
                    process.allocation[i] += request[i]
                    process.need[i] -= request[i]
            
            is_safe, safe_sequence = self._is_safe_state()
            
            if is_safe:
                with process.lock:
                    process.update_need()
                    if process._is_finished():
                        process.status = "Finished"
                    else:
                        process.status = "Running"
                return True, f"Process {process_id}: Request granted. Safe sequence: {safe_sequence}"
            else:
                for i in range(self.num_resources):
                    self.available[i] += request[i]
                    with process.lock:
                        process.allocation[i] -= request[i]
                        process.need[i] += request[i]
                with process.lock:
                    process.update_need()
                    process.status = "Waiting"
                return False, f"Process {process_id}: Request denied - unsafe state would result"
    
    def release_resources(self, process_id: int, release: List[int]) -> str:
        with self.lock:
            process = self.processes[process_id]
            
            with process.lock:
                if any(release[i] > process.allocation[i] for i in range(self.num_resources)):
                    return f"Process {process_id}: Cannot release more than allocated"
                
                for i in range(self.num_resources):
                    process.allocation[i] -= release[i]
                    self.available[i] += release[i]
                
                process.update_need()
                
                if process._is_finished():
                    process.status = "Finished"
                else:
                    process.status = "Running"
            
            return f"Process {process_id}: Released resources {release}"


class ProcessThread(QThread):
    
    action_signal = pyqtSignal(int, str, str)
    log_signal = pyqtSignal(str)
    
    def __init__(self, process_id: int, banker: BankerAlgorithm, 
                 processes: List[Process], num_resources: int, 
                 running: threading.Event):
        super().__init__()
        self.process_id = process_id
        self.banker = banker
        self.processes = processes
        self.num_resources = num_resources
        self.running = running
        self.paused = threading.Event()
        self.paused.set()
        
    def run(self):
        process = self.processes[self.process_id]
        max_iterations = 1000
        iteration = 0
        
        while self.running.is_set() and iteration < max_iterations:
            self.paused.wait()
            
            if not self.running.is_set():
                break
            
            iteration += 1
            
            if process.is_finished():
                time.sleep(0.3)
                continue
            
            action = random.choice(['request', 'release', 'use'])
            
            if action == 'request':
                request = []
                for i in range(self.num_resources):
                    with process.lock:
                        need_val = process.need[i]
                    
                    if need_val > 0:
                        with self.banker.lock:
                            available = self.banker.available[i]
                        
                        if available > 0:
                            max_request = min(need_val, available)
                            if max_request > 0:
                                request_value = random.randint(1, max_request)
                                request.append(request_value)
                            else:
                                request.append(0)
                        else:
                            request.append(0)
                    else:
                        request.append(0)
                
                if any(r > 0 for r in request):
                    success, message = self.banker.request_resources(self.process_id, request)
                    self.log_signal.emit(message)
                    self.action_signal.emit(self.process_id, 'request', 'granted' if success else 'denied')
                else:
                    with process.lock:
                        if any(process.need[i] > 0 for i in range(self.num_resources)):
                            self.log_signal.emit(f"Process {self.process_id}: Waiting for resources...")
            
            elif action == 'release':
                with process.lock:
                    release = []
                    for i in range(self.num_resources):
                        if process.allocation[i] > 0:
                            release_value = random.randint(1, process.allocation[i])
                            release.append(release_value)
                        else:
                            release.append(0)
                
                if any(r > 0 for r in release):
                    message = self.banker.release_resources(self.process_id, release)
                    self.log_signal.emit(message)
                    self.action_signal.emit(self.process_id, 'release', 'success')
            
            elif action == 'use':
                with process.lock:
                    if process.status == "Running" and any(process.allocation[i] > 0 for i in range(self.num_resources)):
                        self.log_signal.emit(f"Process {self.process_id}: Using resources...")
                        self.action_signal.emit(self.process_id, 'use', 'success')
            
            time.sleep(random.uniform(0.3, 0.8))
    
    def pause(self):
        self.paused.clear()
    
    def resume(self):
        self.paused.set()


class MainWindow(QMainWindow):
    
    def __init__(self):
        super().__init__()
        self.num_processes = 5
        self.num_resources = 4
        self.processes: List[Process] = []
        self.banker: Optional[BankerAlgorithm] = None
        self.process_threads: List[ProcessThread] = []
        self.running = threading.Event()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_tables)
        self.check_completion_timer = QTimer()
        self.check_completion_timer.timeout.connect(self.check_all_processes_finished)
        
        self.pink_light = QColor(255, 228, 225)
        self.pink_medium = QColor(255, 192, 203)
        self.pink_dark = QColor(219, 112, 147)
        self.pink_accent = QColor(255, 105, 180)
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("OS Simulator - Banker's Algorithm")
        self.setGeometry(100, 100, 1400, 900)
        
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {self.pink_light.name()};
            }}
            QPushButton {{
                background-color: {self.pink_medium.name()};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self.pink_dark.name()};
            }}
            QPushButton:pressed {{
                background-color: {self.pink_accent.name()};
            }}
            QPushButton:disabled {{
                background-color: #cccccc;
                color: #666666;
            }}
            QGroupBox {{
                font-weight: bold;
                font-size: 13px;
                border: 2px solid {self.pink_dark.name()};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {self.pink_dark.name()};
            }}
            QTableWidget {{
                background-color: white;
                border: 1px solid {self.pink_medium.name()};
                gridline-color: {self.pink_light.name()};
                font-size: 12px;
            }}
            QTableWidget::item {{
                padding: 5px;
            }}
            QHeaderView::section {{
                background-color: {self.pink_medium.name()};
                color: white;
                padding: 8px;
                font-weight: bold;
                border: none;
            }}
            QTextEdit {{
                background-color: white;
                border: 2px solid {self.pink_medium.name()};
                border-radius: 5px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                padding: 5px;
            }}
            QLabel {{
                color: {self.pink_dark.name()};
                font-size: 13px;
                font-weight: bold;
            }}
            QSpinBox {{
                background-color: white;
                border: 2px solid {self.pink_medium.name()};
                border-radius: 5px;
                padding: 5px;
                font-size: 12px;
            }}
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        title = QLabel("🖥️ OS Simulator - Banker's Algorithm for Deadlock Avoidance")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {self.pink_dark.name()}; padding: 10px;")
        main_layout.addWidget(title)
        
        control_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶ Start Simulation")
        self.start_btn.clicked.connect(self.start_simulation)
        control_layout.addWidget(self.start_btn)
        
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.clicked.connect(self.pause_simulation)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)
        
        self.resume_btn = QPushButton("▶ Resume")
        self.resume_btn.clicked.connect(self.resume_simulation)
        self.resume_btn.setEnabled(False)
        control_layout.addWidget(self.resume_btn)
        
        self.reset_btn = QPushButton("🔄 Reset")
        self.reset_btn.clicked.connect(self.reset_simulation)
        control_layout.addWidget(self.reset_btn)
        
        control_layout.addStretch()
        
        config_label = QLabel("Total Resources:")
        control_layout.addWidget(config_label)
        
        self.resource_spinboxes = []
        resource_names = ["CPU", "Memory", "Disk", "Printer"]
        default_values = [4, 6, 3, 2]
        for i, name in enumerate(resource_names):
            label = QLabel(f"{name}:")
            control_layout.addWidget(label)
            spinbox = QSpinBox()
            spinbox.setMinimum(1)
            spinbox.setMaximum(20)
            spinbox.setValue(default_values[i] if i < len(default_values) else 1)
            self.resource_spinboxes.append(spinbox)
            control_layout.addWidget(spinbox)
        
        main_layout.addLayout(control_layout)
        
        content_layout = QHBoxLayout()
        
        left_layout = QVBoxLayout()
        
        available_group = QGroupBox("Available Resources")
        available_layout = QVBoxLayout()
        self.available_table = QTableWidget()
        self.available_table.setColumnCount(self.num_resources)
        self.available_table.setRowCount(1)
        self.available_table.setHorizontalHeaderLabels(["CPU", "Memory", "Disk", "Printer"])
        self.available_table.verticalHeader().setVisible(False)
        self.available_table.setMaximumHeight(80)
        available_layout.addWidget(self.available_table)
        available_group.setLayout(available_layout)
        left_layout.addWidget(available_group)
        
        max_group = QGroupBox("Max Demand (Maximum Resources Needed)")
        max_layout = QVBoxLayout()
        self.max_table = QTableWidget()
        self.max_table.setColumnCount(self.num_resources)
        self.max_table.setRowCount(self.num_processes)
        self.max_table.setHorizontalHeaderLabels(["CPU", "Memory", "Disk", "Printer"])
        self.max_table.setVerticalHeaderLabels([f"P{i}" for i in range(self.num_processes)])
        max_layout.addWidget(self.max_table)
        max_group.setLayout(max_layout)
        left_layout.addWidget(max_group)
        
        alloc_group = QGroupBox("Current Allocation")
        alloc_layout = QVBoxLayout()
        self.alloc_table = QTableWidget()
        self.alloc_table.setColumnCount(self.num_resources)
        self.alloc_table.setRowCount(self.num_processes)
        self.alloc_table.setHorizontalHeaderLabels(["CPU", "Memory", "Disk", "Printer"])
        self.alloc_table.setVerticalHeaderLabels([f"P{i}" for i in range(self.num_processes)])
        alloc_layout.addWidget(self.alloc_table)
        alloc_group.setLayout(alloc_layout)
        left_layout.addWidget(alloc_group)
        
        need_group = QGroupBox("Remaining Need (Max - Allocation)")
        need_layout = QVBoxLayout()
        self.need_table = QTableWidget()
        self.need_table.setColumnCount(self.num_resources)
        self.need_table.setRowCount(self.num_processes)
        self.need_table.setHorizontalHeaderLabels(["CPU", "Memory", "Disk", "Printer"])
        self.need_table.setVerticalHeaderLabels([f"P{i}" for i in range(self.num_processes)])
        need_layout.addWidget(self.need_table)
        need_group.setLayout(need_layout)
        left_layout.addWidget(need_group)
        
        status_group = QGroupBox("Process Status")
        status_layout = QVBoxLayout()
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(2)
        self.status_table.setRowCount(self.num_processes)
        self.status_table.setHorizontalHeaderLabels(["Process", "Status"])
        self.status_table.setVerticalHeaderLabels([f"P{i}" for i in range(self.num_processes)])
        self.status_table.setColumnWidth(0, 100)
        self.status_table.setColumnWidth(1, 150)
        status_layout.addWidget(self.status_table)
        status_group.setLayout(status_layout)
        left_layout.addWidget(status_group)
        
        content_layout.addLayout(left_layout, 2)
        
        log_group = QGroupBox("Simulation Logs")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumWidth(400)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        content_layout.addWidget(log_group, 1)
        
        main_layout.addLayout(content_layout)
        
        self.statusBar().showMessage("Ready to start simulation")
        self.statusBar().setStyleSheet(f"background-color: {self.pink_light.name()};")
        
        QTimer.singleShot(100, self.setup_initial_state)
    
    def setup_initial_state(self):
        self.reset_simulation()
    
    def generate_random_max_demand(self, total_resources: List[int]) -> List[List[int]]:
        max_demands = []
        for process_idx in range(self.num_processes):
            demand = []
            for res_idx in range(self.num_resources):
                max_possible = total_resources[res_idx]
                upper_limit = min(max_possible, max(1, max_possible * 2 // 3))
                value = random.randint(0, upper_limit)
                demand.append(value)
            
            if all(d == 0 for d in demand):
                demand[random.randint(0, self.num_resources - 1)] = 1
            
            max_demands.append(demand)
        
        for res_idx in range(self.num_resources):
            total_demand = sum(max_demands[i][res_idx] for i in range(self.num_processes))
            max_allowed = total_resources[res_idx] * self.num_processes // 2
            
            if total_demand > max_allowed:
                scale_factor = max_allowed / total_demand if total_demand > 0 else 1
                for i in range(self.num_processes):
                    max_demands[i][res_idx] = max(0, int(max_demands[i][res_idx] * scale_factor))
        
        return max_demands
    
    def initial_safe_allocation(self):
        is_safe, seq = self.banker.is_safe_state()
        if not is_safe or not seq:
            return
        
        num_to_allocate = min(3, len(self.processes))
        for idx in range(num_to_allocate):
            if idx >= len(seq):
                break
            process_id = seq[idx]
            process = self.processes[process_id]
            
            request = []
            for res_idx in range(self.num_resources):
                with process.lock:
                    need_val = process.need[res_idx]
                
                if need_val > 0:
                    with self.banker.lock:
                        available_val = self.banker.available[res_idx]
                    
                    if available_val > 0:
                        max_possible = min(need_val, available_val)
                        amount = random.randint(1, max_possible)
                        request.append(amount)
                    else:
                        request.append(0)
                else:
                    request.append(0)
            
            if any(r > 0 for r in request):
                success, _ = self.banker.request_resources(process_id, request)
    
    def reset_simulation(self):
        self.stop_all_threads()
        
        self.running = threading.Event()
        
        total_resources = [sb.value() for sb in self.resource_spinboxes]
        
        max_demands = self.generate_random_max_demand(total_resources)
        
        self.processes = [
            Process(i, max_demands[i])
            for i in range(self.num_processes)
        ]
        
        self.banker = BankerAlgorithm(
            self.num_processes,
            self.num_resources,
            total_resources.copy(),
            self.processes
        )
        
        self.initial_safe_allocation()
        
        self.update_tables()
        self.log_text.clear()
        self.log_text.append("=== Simulation Reset ===\n")
        self.log_text.append(f"Total Resources: {total_resources}\n")
        self.log_text.append("Resource Types: CPU, Memory, Disk, Printer\n")
        self.log_text.append(f"Number of Processes: {self.num_processes}\n")
        self.log_text.append("\nMax Demands (Maximum resources each process needs):\n")
        for i, demand in enumerate(max_demands):
            self.log_text.append(f"  Process {i}: {demand}\n")
        
        is_safe, safe_sequence = self.banker.is_safe_state()
        if is_safe:
            self.log_text.append(f"\nInitial state is SAFE.\n")
            self.log_text.append(f"Safe sequence: {safe_sequence}\n")
        else:
            self.log_text.append("\nWARNING: Initial state is UNSAFE!\n")
        
        self.log_text.append("\nReady to start simulation...\n")
        self.log_text.append("You can adjust resource values using the spinboxes above.\n")
        
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.statusBar().showMessage("Simulation reset. Ready to start.")
    
    def stop_all_threads(self):
        if self.process_threads:
            self.running.clear()
            for thread in self.process_threads:
                if thread.isRunning():
                    thread.resume()
                    thread.wait(2000)
                    if thread.isRunning():
                        thread.terminate()
                        thread.wait()
            self.process_threads.clear()
        
        if self.update_timer.isActive():
            self.update_timer.stop()
        
        if self.check_completion_timer.isActive():
            self.check_completion_timer.stop()
    
    def start_simulation(self):
        if not self.banker:
            return
        
        if self.process_threads:
            return
        
        self.running.set()
        
        self.process_threads = []
        for i in range(self.num_processes):
            thread = ProcessThread(
                i,
                self.banker,
                self.processes,
                self.num_resources,
                self.running
            )
            thread.log_signal.connect(self.add_log)
            thread.action_signal.connect(self.on_process_action)
            self.process_threads.append(thread)
            thread.start()
        
        self.update_timer.start(300)
        self.check_completion_timer.start(1000)
        
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.statusBar().showMessage("Simulation running...")
        
        self.add_log("=== Simulation Started ===")
    
    def pause_simulation(self):
        if self.process_threads:
            for thread in self.process_threads:
                if thread.isRunning():
                    thread.pause()
            self.update_timer.stop()
            self.check_completion_timer.stop()
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.statusBar().showMessage("Simulation paused")
            self.add_log("=== Simulation Paused ===")
    
    def resume_simulation(self):
        if self.process_threads:
            for thread in self.process_threads:
                if thread.isRunning():
                    thread.resume()
            self.update_timer.start(300)
            self.check_completion_timer.start(1000)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.statusBar().showMessage("Simulation running...")
            self.add_log("=== Simulation Resumed ===")
    
    def on_process_action(self, process_id: int, action: str, result: str):
        self.update_tables()
    
    def check_all_processes_finished(self):
        if not self.processes or not self.process_threads:
            return
        
        all_finished = True
        for process in self.processes:
            if not process.is_finished():
                all_finished = False
                break
        
        if all_finished:
            self.stop_all_threads()
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
            self.statusBar().showMessage("All processes finished!")
            self.add_log("=== All Processes Finished ===")
            
            is_safe, safe_sequence = self.banker.is_safe_state()
            if is_safe:
                self.add_log(f"Final state is SAFE. Safe sequence: {safe_sequence}")
            else:
                self.add_log("Final state is UNSAFE!")
    
    def add_log(self, message: str):
        self.log_text.append(message)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def update_tables(self):
        if not self.banker:
            return
        
        with self.banker.lock:
            available = self.banker.available.copy()
        
        for i in range(self.num_resources):
            item = QTableWidgetItem(str(available[i]))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.available_table.setItem(0, i, item)
        
        for i in range(self.num_processes):
            with self.processes[i].lock:
                max_demand = self.processes[i].max_demand.copy()
                allocation = self.processes[i].allocation.copy()
                need = self.processes[i].need.copy()
                status = self.processes[i].status
            
            for j in range(self.num_resources):
                item = QTableWidgetItem(str(max_demand[j]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.max_table.setItem(i, j, item)
            
            for j in range(self.num_resources):
                item = QTableWidgetItem(str(allocation[j]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if allocation[j] > 0:
                    item.setBackground(QColor(200, 255, 200))
                self.alloc_table.setItem(i, j, item)
            
            for j in range(self.num_resources):
                item = QTableWidgetItem(str(need[j]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if need[j] > 0:
                    item.setBackground(QColor(255, 200, 200))
                else:
                    item.setBackground(QColor(200, 255, 200))
                self.need_table.setItem(i, j, item)
            
            pid_item = QTableWidgetItem(f"Process {i}")
            pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.status_table.setItem(i, 0, pid_item)
            
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            if status == "Running":
                status_item.setBackground(QColor(144, 238, 144))
            elif status == "Waiting":
                status_item.setBackground(QColor(255, 182, 193))
            elif status == "Finished":
                status_item.setBackground(QColor(173, 216, 230))
            
            self.status_table.setItem(i, 1, status_item)
        
        is_safe, safe_sequence = self.banker.is_safe_state()
        if is_safe:
            self.statusBar().showMessage(
                f"State is SAFE. Safe sequence: {safe_sequence}"
            )
        else:
            self.statusBar().showMessage("State is UNSAFE - potential deadlock!")


def main():
    app = QApplication(sys.argv)
    
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
