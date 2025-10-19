import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import subprocess
import json
import os
import sys
import platform
import math
import time

# ====================================================================
# EMBEDDED C CODE (Priority + Banker's + Paging)
# ====================================================================

C_SOURCE_CODE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include <time.h>
#include <string.h>

// Dynamic Settings (initialized from command-line arguments)
int NUM_PROCESSES = 5; 
int TOTAL_FRAMES = 5;       // Now represents total memory frames
int PAGE_SIZE = 1;          // Simplified: one memory block is one frame
int QUANTUM_SECONDS = 2;   

// CONSTANTS
#define MAX_BURST_TIME 5
#define MIN_BURST_TIME 3
#define MAX_MEM_REQ 4      // Max frames needed by process
#define MIN_MEM_REQ 1
#define MAX_PRIORITY 5     // Lower number is higher priority (1-5)
#define MIN_PRIORITY 1
#define STARVATION_THRESHOLD 10
#define MAX_TIMELINE_SIZE 1000 
#define MAX_PAGES 50       // Safety limit for page/frame table

#define WAITING 0
#define RUNNING 1
#define FINISHED 2

// Process structure
typedef struct {
    int id;
    int priority;         // 1 (Highest) to MAX_PRIORITY (Lowest)
    int burst_time;       // Total time needed
    int remaining_time;   // Time left
    int mem_needed;       // Current frames requested
    int max_mem;          // Max frames process will EVER need (Banker's)
    int mem_allocated;    // Current frames allocated
    int page_table[MAX_PAGES]; // Stores frame IDs for this process
    int page_table_count; 
    int state;
    int arrival_time;
    int start_time;
    int completion_time;
    int waiting_time;
    int turnaround_time;
    int idle_cycles;      
    char status[50];      
} ProcessInfo;

ProcessInfo *processes; 
int current_time = 0;
int time_total_burst = 0; 
int timeline[MAX_TIMELINE_SIZE];
int timeCount = 0;
int memory_frames[MAX_PAGES]; // 0: Free, >0: PID occupying the frame

// Dynamic Settings
char ALGORITHM[10]; 

// Synchronization Objects 
HANDLE cpu_semaphore; 
HANDLE mem_mutex; // Using a Mutex for memory array access and safety check

// ====================================================================
// BANKER'S ALGORITHM (Safety Check)
// ====================================================================

// Checks if allocating 'request' frames to 'pid' is safe
int check_safety(int pid, int request) {
    int i, j;
    int available[MAX_PAGES];
    int work[MAX_PAGES];
    int finish[MAX_PAGES];
    int allocation[MAX_PAGES];
    int need[MAX_PAGES];
    int num_proc = NUM_PROCESSES;
    int num_res = 1; // Only memory frames are considered

    // 1. Calculate current available frames
    int free_frames = 0;
    for(i=0; i < TOTAL_FRAMES; i++) {
        if (memory_frames[i] == 0) {
            free_frames++;
        }
    }
    available[0] = free_frames - request; // Tentative available after allocation

    // 2. Initialize Work and Finish
    work[0] = available[0];
    for (i = 0; i < num_proc; i++) {
        finish[i] = 0;
    }

    // 3. Initialize Allocation and Need (tentative state)
    for (i = 0; i < num_proc; i++) {
        // Tentative Allocation: current + request (for the requesting process)
        allocation[i] = processes[i].mem_allocated;
        if (processes[i].id == pid) {
            allocation[i] += request;
        }
        
        // Need
        need[i] = processes[i].max_mem - allocation[i];
    }
    
    // Safety check loop
    int safe_count = 0;
    int found;
    do {
        found = 0;
        for (i = 0; i < num_proc; i++) {
            if (processes[i].state == FINISHED || processes[i].remaining_time <= 0) {
                 finish[i] = 1; // Finished processes are always considered done
                 continue;
            }
            if (finish[i] == 0 && need[i] <= work[0]) {
                work[0] += allocation[i];
                finish[i] = 1;
                found = 1;
                safe_count++;
            }
        }
    } while (found);

    // 4. Check if all non-finished processes can finish
    for (i = 0; i < num_proc; i++) {
        if (processes[i].state != FINISHED && processes[i].remaining_time > 0 && finish[i] == 0) {
            return 0; // Unsafe state
        }
    }
    return 1; // Safe state
}

// ====================================================================
// LOGGING FUNCTIONS
// ====================================================================

void logSnapshot() {
    FILE *f = fopen("events.log", "a");
    if (!f) return;

    int allocated_frames = 0;
    for (int i = 0; i < TOTAL_FRAMES; i++) {
        if (memory_frames[i] != 0) allocated_frames++;
    }
    int available_frames = TOTAL_FRAMES - allocated_frames;

    fprintf(f, "{");
    fprintf(f, "\"time\": %d,", current_time);
    
    // Check CPU status non-blockingly for logging
    DWORD result = WaitForSingleObject(cpu_semaphore, 0); 
    char* cpu_status = (result == WAIT_OBJECT_0) ? "Available" : "Busy";
    if (result == WAIT_OBJECT_0) {
        ReleaseSemaphore(cpu_semaphore, 1, NULL); 
    }

    fprintf(f, "\"resources\":{");
    fprintf(f, "\"cpu_status\":\"%s\",", cpu_status);
    fprintf(f, "\"mem_max\": %d,", TOTAL_FRAMES);
    fprintf(f, "\"mem_available\":%d", available_frames);
    fprintf(f, "},");

    fprintf(f, "\"processes\":[");
    for (int i = 0; i < NUM_PROCESSES; i++) {
        fprintf(f,
            "{\"id\":%d,\"prio\":%d,\"burst\":%d,\"remaining\":%d,\"mem_needed\":%d,\"max_mem\":%d,\"mem_allocated\":%d,\"status\":\"%s\"}",
            processes[i].id,
            processes[i].priority,
            processes[i].burst_time,
            processes[i].remaining_time,
            processes[i].mem_needed,
            processes[i].max_mem,
            processes[i].mem_allocated,
            processes[i].status
        );
        if (i < NUM_PROCESSES - 1) fprintf(f, ",");
    }
    fprintf(f, "],");
    
    fprintf(f, "\"timeline\":[");
    for (int k = 0; k < timeCount; k++) {
        fprintf(f, "\"P%d\"", timeline[k]);
        if (k < timeCount - 1) fprintf(f, ",");
    }
    fprintf(f, "]");
    fprintf(f, "}\n");
    fflush(f);
    fclose(f);
}

void updateStatus(int i, int is_critical) {
    if (processes[i].state == FINISHED) strcpy(processes[i].status, "Completed");
    else if (processes[i].state == RUNNING) {
        if (is_critical) strcpy(processes[i].status, "Critical Section");
        else strcpy(processes[i].status, "Running");
    }
    else {
        // Advanced status: Check for memory waiting first
        if (processes[i].idle_cycles > STARVATION_THRESHOLD) strcpy(processes[i].status, "STARVATION DANGER");
        else if (processes[i].mem_allocated < processes[i].mem_needed) strcpy(processes[i].status, "Waiting (Memory/Banker)");
        else strcpy(processes[i].status, "Waiting (CPU)"); 
    }
}

// ====================================================================
// PAGING/MEMORY MANAGEMENT
// ====================================================================

// Finds the first 'count' free frames and marks them for 'pid'
int allocate_frames(int pid, int count) {
    int allocated_count = 0;
    for (int i = 0; i < TOTAL_FRAMES && allocated_count < count; i++) {
        if (memory_frames[i] == 0) {
            memory_frames[i] = processes[pid].id;
            processes[pid].page_table[processes[pid].page_table_count++] = i + 1; // Store frame ID (1-based)
            processes[pid].mem_allocated++;
            allocated_count++;
        }
    }
    return allocated_count == count;
}

// Releases all frames held by 'pid'
void release_frames(int pid) {
    for (int i = 0; i < TOTAL_FRAMES; i++) {
        if (memory_frames[i] == processes[pid].id) {
            memory_frames[i] = 0; // Release frame
        }
    }
    processes[pid].mem_allocated = 0;
    processes[pid].page_table_count = 0;
}

// ====================================================================
// SYNCHRONIZATION AND BANKER-INTEGRATED ACQUISITION
// ====================================================================

int acquire_cpu(int pid) {
    DWORD result = WaitForSingleObject(cpu_semaphore, 0); 
    return (result == WAIT_OBJECT_0);
}

void release_cpu(int pid) {
    ReleaseSemaphore(cpu_semaphore, 1, NULL);
}

int acquire_memory(int pid) {
    int needed = processes[pid].mem_needed - processes[pid].mem_allocated;
    
    if (needed <= 0) return 1; 

    WaitForSingleObject(mem_mutex, INFINITE); 
    
    // 1. BANKER'S ALGORITHM CHECK: Is the request safe?
    if (!check_safety(processes[pid].id, needed)) {
        ReleaseMutex(mem_mutex);
        strcpy(processes[pid].status, "Waiting (Banker Denied)");
        return 0; // Banker's denies the request for safety
    }

    // 2. PHYSICAL FRAME ALLOCATION (PAGING)
    if (!allocate_frames(pid, needed)) {
        // Should theoretically not fail if Banker passed and there was a free frame, 
        // but log the denial just in case of resource race/timing issues not captured by mutex.
        ReleaseMutex(mem_mutex);
        strcpy(processes[pid].status, "Waiting (No Free Frames)");
        return 0; 
    }
    
    ReleaseMutex(mem_mutex);
    return 1; 
}

void release_memory(int pid) {
    WaitForSingleObject(mem_mutex, INFINITE);
    release_frames(pid);
    ReleaseMutex(mem_mutex);
}

// ====================================================================
// SCHEDULER (Priority Preemptive + RR/FCFS)
// ====================================================================

void scheduler() {
    int completed = 0;
    int is_rr = (strcmp(ALGORITHM, "RR") == 0);
    int quantum_s = QUANTUM_SECONDS;
    
    while (completed < NUM_PROCESSES) {
        int did_something = 0;
        int next_pid_to_run = -1;
        int highest_prio = MAX_PRIORITY + 1;

        // 1. PRIORITY SELECTION
        for (int i = 0; i < NUM_PROCESSES; i++) {
            if (processes[i].state != FINISHED && processes[i].remaining_time > 0) {
                if (processes[i].priority < highest_prio) {
                    highest_prio = processes[i].priority;
                    next_pid_to_run = i; 
                } else if (processes[i].priority == highest_prio) {
                    // Tie-breaker: FCFS by arrival time (default 0)
                    if (next_pid_to_run == -1 || processes[i].arrival_time < processes[next_pid_to_run].arrival_time) {
                         next_pid_to_run = i;
                    }
                }
            }
        }
        
        if (next_pid_to_run == -1) {
            if (completed < NUM_PROCESSES) Sleep(100); 
            continue;
        }

        int i = next_pid_to_run;

        // 2. Memory Pre-check
        if (processes[i].mem_allocated < processes[i].mem_needed) {
            if (!acquire_memory(i)) {
                // Denied by Banker or No Frames, process must wait
                processes[i].state = WAITING;
                processes[i].idle_cycles++;
                updateStatus(i, 0);
                did_something = 1;
                logSnapshot();
                continue; 
            }
        } else {
            processes[i].idle_cycles = 0; 
        }

        // 3. CPU Acquisition (Only the highest priority process attempts CPU)
        if (processes[i].mem_allocated == processes[i].mem_needed && acquire_cpu(i)) {
            
            did_something = 1;
            processes[i].state = RUNNING;
            updateStatus(i, 1); 
            if (processes[i].start_time == -1) processes[i].start_time = current_time;
            
            logSnapshot(); 
            
            int execTime;
            if (is_rr) {
                 execTime = (processes[i].remaining_time > quantum_s) ? quantum_s : processes[i].remaining_time;
            } else {
                 // FCFS: run for 1 second per step for logging/visualization.
                 execTime = (processes[i].remaining_time > 0) ? 1 : 0; 
            }
            
            Sleep(execTime * 1000); 

            current_time += execTime;
            processes[i].remaining_time -= execTime;
            if (timeCount < MAX_TIMELINE_SIZE) {
                timeline[timeCount++] = processes[i].id;
            }
            
            if (processes[i].remaining_time <= 0) {
                // 3a. Process finished
                processes[i].state = FINISHED;
                updateStatus(i, 0);
                processes[i].completion_time = current_time;
                processes[i].turnaround_time = processes[i].completion_time - processes[i].arrival_time;
                processes[i].waiting_time = processes[i].turnaround_time - processes[i].burst_time;
                completed++;
                
                release_memory(i);
                release_cpu(i);
                
            } else {
                // 3b. Preemption/Step end (Always preempt after burst/quantum to check for higher prio)
                processes[i].state = WAITING;
                updateStatus(i, 0);
                release_cpu(i); 
            }
            
            logSnapshot(); 
        } else if (processes[i].mem_allocated == processes[i].mem_needed) {
            // Memory acquired, but CPU busy
            processes[i].state = WAITING;
            processes[i].idle_cycles++;
            updateStatus(i, 0);
            did_something = 1;
            logSnapshot();
        } else {
            // Memory not acquired (Banker/No Frames), waiting is handled in 2.
            processes[i].idle_cycles++;
            did_something = 1; 
            if (processes[i].idle_cycles > STARVATION_THRESHOLD && strcmp(processes[i].status, "STARVATION DANGER") != 0) {
                 updateStatus(i, 0);
                 logSnapshot();
            }
        }

        if (completed < NUM_PROCESSES && !did_something) Sleep(100); 
    }
}

// ====================================================================
// FINAL OUTPUT
// ====================================================================

void writeLogsToJSON() {
    FILE *fp = fopen("output.json", "w");
    if (!fp) return;
    
    int allocated_frames = 0;
    for (int i = 0; i < TOTAL_FRAMES; i++) {
        if (memory_frames[i] != 0) allocated_frames++;
    }
    int final_mem_available = TOTAL_FRAMES - allocated_frames; 

    fprintf(fp, "{\n");
    fprintf(fp, "  \"numProcesses\": %d,\n", NUM_PROCESSES);
    fprintf(fp, "  \"totalTime\": %d,\n", current_time);
    fprintf(fp, "  \"totalBurstTime\": %d,\n", time_total_burst);
    fprintf(fp, "  \"algorithm\": \"%s\",\n", ALGORITHM);
    
    fprintf(fp, "  \"timeline\": [");
    for (int i = 0; i < timeCount; i++) {
        fprintf(fp, "\"P%d\"", timeline[i]);
        if (i < timeCount - 1) fprintf(fp, ", ");
    }
    fprintf(fp, "],\n  \"processes\": [\n");
    for (int i = 0; i < NUM_PROCESSES; i++) {
        fprintf(fp, "    { \"id\": %d, \"prio\": %d, \"burst\": %d, \"memNeeded\": %d, \"maxMem\": %d, \"completion\": %d, \"turnaroundTime\": %d, \"waitingTime\": %d, \"status\": \"%s\" }",
                processes[i].id, processes[i].priority, processes[i].burst_time, processes[i].mem_needed, processes[i].max_mem,
                processes[i].completion_time, processes[i].turnaround_time, processes[i].waiting_time, processes[i].status);
        if (i < NUM_PROCESSES - 1) fprintf(fp, ",\n"); else fprintf(fp, "\n");
    }
    fprintf(fp, "  ],\n  \"resources\": {\n    \"cpu_max\": 1,\n    \"mem_max\": %d,\n    \"cpu_status\": \"Available\",\n    \"mem_available\": %d\n  }\n}\n", 
            TOTAL_FRAMES, final_mem_available);
    fclose(fp);
}

// ====================================================================
// MAIN ENTRY POINT
// ====================================================================

int main(int argc, char *argv[]) {
    // Argument Parsing: [0]=exe, [1]=Algorithm, [2]=Quantum, [3]=TotalFrames, [4]=PageSize, [5]=NumProcesses
    if (argc != 6) {
        return 1; // Critical failure if args are missing
    } else {
        strcpy(ALGORITHM, argv[1]);
        QUANTUM_SECONDS = atoi(argv[2]);
        TOTAL_FRAMES = atoi(argv[3]);
        PAGE_SIZE = atoi(argv[4]); // Included for completeness but ignored in simplified model
        NUM_PROCESSES = atoi(argv[5]);
        
        if (NUM_PROCESSES <= 0 || NUM_PROCESSES > 50) NUM_PROCESSES = 5; 
        if (TOTAL_FRAMES <= 0 || TOTAL_FRAMES > MAX_PAGES) TOTAL_FRAMES = 5; 
        if (QUANTUM_SECONDS <= 0) QUANTUM_SECONDS = 2; 
    }
    
    srand((unsigned)time(NULL));
    FILE *fe = fopen("events.log", "w"); if (fe) fclose(fe);

    // Dynamic Allocation of Processes array
    processes = (ProcessInfo *)malloc(NUM_PROCESSES * sizeof(ProcessInfo));
    if (processes == NULL) return 1;
    memset(memory_frames, 0, sizeof(memory_frames));

    // Initialize Semaphores/Mutex
    cpu_semaphore = CreateSemaphore(NULL, 1, 1, "CPUSemaphore");
    mem_mutex = CreateMutex(NULL, FALSE, "MemMutex"); // Mutex to protect shared memory structures
    
    if (cpu_semaphore == NULL || mem_mutex == NULL) {
        free(processes);
        return 1;
    }

    // Initialize Processes
    for (int i = 0; i < NUM_PROCESSES; i++) {
        processes[i].id = i + 1;
        processes[i].priority = (rand() % (MAX_PRIORITY - MIN_PRIORITY + 1)) + MIN_PRIORITY; // Priority
        processes[i].burst_time = (rand() % (MAX_BURST_TIME - MIN_BURST_TIME + 1)) + MIN_BURST_TIME;
        processes[i].remaining_time = processes[i].burst_time;
        processes[i].mem_needed = (rand() % (MAX_MEM_REQ - MIN_MEM_REQ + 1)) + MIN_MEM_REQ; // Frames needed
        processes[i].max_mem = (rand() % (MAX_MEM_REQ - processes[i].mem_needed + 1)) + processes[i].mem_needed; // Max frames (Banker)
        processes[i].mem_allocated = 0;
        processes[i].page_table_count = 0;
        processes[i].state = WAITING;
        processes[i].idle_cycles = 0;
        strcpy(processes[i].status, "Waiting (CPU)"); 
        processes[i].arrival_time = 0;
        processes[i].start_time = -1;
        processes[i].completion_time = 0;
        processes[i].waiting_time = 0;
        processes[i].turnaround_time = 0;
        
        time_total_burst += processes[i].burst_time;
    }
    
    logSnapshot();
    
    scheduler();
    
    writeLogsToJSON();
    
    CloseHandle(cpu_semaphore);
    CloseHandle(mem_mutex);
    free(processes); 
    
    return 0;
}
"""

# ====================================================================
# PYTHON GUI CODE (Tkinter) - Updated for new features
# ====================================================================

class SemaphoreUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OS Resource Allocation")
        self.geometry("1850x880") 
        self.configure(bg="#f6f8fa")
        self.snapshots = []
        self.current_snapshot_index = -1
        self.snapshot_count = 0
        self.process_colors = ["#7dc3f2", "#f29f7d", "#a6d37a", "#d57dd6", "#f2e27d", "#ff99e6", "#99ff99", "#ffcc66", "#6699ff", "#ff6666", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8"]
        self.create_widgets()
        self.style_widgets()
        
        if platform.system() != 'Windows':
            messagebox.showwarning("OS Warning", "The C code uses Windows API (windows.h) for synchronization. "
                                                 "Compilation and execution may fail on Linux/macOS unless GCC has the necessary compatibility libraries.")

    def create_widgets(self):
        # Top control bar (Dark Background)
        top = tk.Frame(self, bg="#0f1724", height=70)
        top.pack(fill=tk.X, side=tk.TOP)

        title = tk.Label(top, text="OS Resource Allocation", bg="#0f1724", fg="white",
                             font=("Segoe UI", 16, "bold"))
        title.pack(side=tk.LEFT, padx=20, pady=12)

        # --- Settings Frame (Packed to the RIGHT) ---
        settings_frame = tk.Frame(top, bg="#0f1724")
        settings_frame.pack(side=tk.RIGHT, padx=12, pady=6)

        # Num Processes Input 
        tk.Label(settings_frame, text="Processes:", bg="#0f1724", fg="#cbd5e1", font=("Segoe UI", 10)).grid(row=0, column=0, padx=(10, 2))
        self.num_proc_var = tk.StringVar(value="8") 
        tk.Entry(settings_frame, textvariable=self.num_proc_var, width=4).grid(row=0, column=1, padx=(0, 10))

        # Algorithm Selector
        tk.Label(settings_frame, text="Algo:", bg="#0f1724", fg="#cbd5e1", font=("Segoe UI", 10)).grid(row=0, column=2, padx=(10, 2))
        self.algo_var = tk.StringVar(value="RR")
        ttk.Combobox(settings_frame, textvariable=self.algo_var, values=["RR", "FCFS"], width=6, state="readonly").grid(row=0, column=3, padx=(0, 10))

        # Quantum Input
        tk.Label(settings_frame, text="Quantum (s):", bg="#0f1724", fg="#cbd5e1", font=("Segoe UI", 10)).grid(row=0, column=4, padx=(10, 2))
        self.quantum_var = tk.StringVar(value="2")
        tk.Entry(settings_frame, textvariable=self.quantum_var, width=4).grid(row=0, column=5, padx=(0, 10))
        
        # Total Frames Input (Max Mem)
        tk.Label(settings_frame, text="Total Frames:", bg="#0f1724", fg="#cbd5e1", font=("Segoe UI", 10)).grid(row=0, column=6, padx=(10, 2))
        self.mem_var = tk.StringVar(value="12")
        tk.Entry(settings_frame, textvariable=self.mem_var, width=4).grid(row=0, column=7, padx=(0, 10))
        
        # Page Size Input (Simplified model uses 1, but keep UI for completeness)
        tk.Label(settings_frame, text="Page Size (KB):", bg="#0f1724", fg="#cbd5e1", font=("Segoe UI", 10)).grid(row=0, column=8, padx=(10, 2))
        self.page_size_var = tk.StringVar(value="1")
        tk.Entry(settings_frame, textvariable=self.page_size_var, width=4).grid(row=0, column=9, padx=(0, 20))


        # --- BUTTONS RELOCATED TO A SEPARATE FRAME BELOW THE HEADER ---
        
        button_frame = tk.Frame(self, bg="#e6eef6", pady=8)
        button_frame.pack(fill=tk.X, side=tk.TOP)
        
        # Start Button
        self.start_btn = tk.Button(button_frame, text="▶ Start Simulation", command=self.start_simulation,
                                     bg="#10b981", fg="white", font=("Segoe UI", 10, "bold"), padx=12, pady=6)
        self.start_btn.pack(side=tk.LEFT, padx=(20, 10)) 

        # Prev Step Button
        self.prev_btn = tk.Button(button_frame, text="⏮ Prev Step", command=self.show_prev_snapshot, state=tk.DISABLED,
                                     bg="#64748b", fg="white", font=("Segoe UI", 10), padx=10, pady=6)
        self.prev_btn.pack(side=tk.LEFT, padx=6)

        # Next Step Button
        self.next_btn = tk.Button(button_frame, text="Next Step ⏭", command=self.show_next_snapshot, state=tk.DISABLED,
                                     bg="#64748b", fg="white", font=("Segoe UI", 10), padx=10, pady=6)
        self.next_btn.pack(side=tk.LEFT, padx=6)

        # Step Label
        self.step_label = tk.Label(button_frame, text="Step: 0/0 (Time: 0s)", bg="#e6eef6", fg="#0f1724", font=("Segoe UI", 10, "bold"))
        self.step_label.pack(side=tk.LEFT, padx=12)


        # Main area
        main = tk.Frame(self, bg="#f6f8fa")
        main.pack(fill=tk.BOTH, expand=True, padx=14, pady=(12,14))

        # Left panel — Process table and details
        left = tk.Frame(main, bg="#f6f8fa")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))

        # Resource Gauges Card
        gauge_card = tk.Frame(left, bg="white", bd=0, relief=tk.RIDGE)
        gauge_card.pack(fill=tk.X, pady=(0,8))
        tk.Label(gauge_card, text="Resource Utilization (Gauges)", bg="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10,0))
        
        gauge_frame = tk.Frame(gauge_card, bg="white")
        gauge_frame.pack(fill=tk.X, padx=12, pady=(6,6))

        tk.Label(gauge_frame, text="CPU (Binary Semaphore):", bg="white", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.cpu_gauge = ttk.Progressbar(gauge_frame, orient="horizontal", length=200, mode="determinate")
        self.cpu_gauge.grid(row=0, column=1, sticky="w")
        self.cpu_label = tk.Label(gauge_frame, text="[N/A]", bg="white", font=("Segoe UI", 10, "italic"), width=10)
        self.cpu_label.grid(row=0, column=2, sticky="w", padx=(10, 0))

        tk.Label(gauge_frame, text="Memory (Total Frames):", bg="white", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(4,0))
        self.mem_gauge = ttk.Progressbar(gauge_frame, orient="horizontal", length=200, mode="determinate")
        self.mem_gauge.grid(row=1, column=1, sticky="w", pady=(4,0))
        self.mem_label = tk.Label(gauge_frame, text="[N/A]", bg="white", font=("Segoe UI", 10, "italic"), width=10)
        self.mem_label.grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(4,0))
        
        # --- ADVANCED RESOURCE UTILIZATION (Contention Metrics) ---
        contention_frame = tk.Frame(gauge_card, bg="white")
        contention_frame.pack(fill=tk.X, padx=12, pady=(0, 12)) 

        tk.Label(contention_frame, text="Resource Contention Metrics:", bg="white", font=("Segoe UI", 10, "bold"), fg="#1e40af").pack(anchor="w", pady=(4, 2))

        self.cpu_contention_label = tk.Label(contention_frame, text="Processes Waiting for CPU: N/A", bg="white", font=("Segoe UI", 9), anchor="w", fg="#475569")
        self.cpu_contention_label.pack(fill=tk.X)

        self.mem_contention_label = tk.Label(contention_frame, text="Processes Waiting for Memory: N/A (Including Banker's Denial)", bg="white", font=("Segoe UI", 9), anchor="w", fg="#475569")
        self.mem_contention_label.pack(fill=tk.X)
        # -----------------------------------------------------------------


        # Process table card
        card_proc = tk.Frame(left, bg="white")
        card_proc.pack(fill=tk.BOTH, expand=True)

        tk.Label(card_proc, text="Process States", bg="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(12,6))

        columns = ("PID", "Prio", "Burst (s)", "Remaining (s)", "Mem Req", "Max Mem (Banker's)", "Frames Alloc", "Status")
        self.tree = ttk.Treeview(card_proc, columns=columns, show="headings", height=10)
        
        col_widths = {"PID": 50, "Prio": 50, "Burst (s)": 80, "Remaining (s)": 100, "Mem Req": 80, "Max Mem (Banker's)": 130, "Frames Alloc": 100, "Status": 180}
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=col_widths.get(col, 80))
        
        self.tree.tag_configure("Critical Section", background="#ffeb3b", foreground="#333333")
        self.tree.tag_configure("STARVATION DANGER", background="#ef9a9a", foreground="#b71c1c")
        self.tree.tag_configure("Banker Denied", background="#ffb347", foreground="#333333")

        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,12))

        # Right panel — Timeline (Gantt) and final report
        right = tk.Frame(main, bg="#f6f8fa", width=420)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # Gantt card
        gantt_card = tk.Frame(right, bg="white")
        gantt_card.pack(fill=tk.X, pady=(0,8))

        tk.Label(gantt_card, text="Execution Timeline (Gantt)", bg="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10,6))
        self.gantt_canvas = tk.Canvas(gantt_card, height=160, bg="#f8fafc", highlightthickness=0)
        self.gantt_canvas.pack(fill=tk.X, padx=12, pady=(0,12))

        # Report card
        report_card = tk.Frame(right, bg="white")
        report_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(report_card, text="Final Performance Report", bg="white", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(12,6))
        
        # New Performance Metrics Label
        self.metrics_label = tk.Label(report_card, text="Metrics: CPU Util: N/A | Total Time: N/A", bg="white", font=("Segoe UI", 10, "bold"), anchor="w", fg="#10b981")
        self.metrics_label.pack(fill=tk.X, padx=12)

        self.report_text = scrolledtext.ScrolledText(report_card, width=40, height=10, state=tk.DISABLED, font=("Consolas", 10))
        self.report_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,12))

        # Status bar
        self.status_bar = tk.Label(self, text="Ready", anchor="w", bg="#e6eef6", fg="#0f1724", font=("Segoe UI", 9))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def style_widgets(self):
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=26)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[('selected', '#cdebf9')])
        style.configure("TProgressbar", thickness=15)
        style.map("TProgressbar", background=[('selected', '#cdebf9'), ('active', '#4338ca')])

    # -------------------- Simulation / compile / run --------------------
    def start_simulation(self):
        c_file = "semaphore_simulator.c"
        exe_name = "semaphore_simulator.exe" if platform.system() == 'Windows' else "semaphore_simulator"
        
        # 0. Get user inputs and validate
        try:
            algo = self.algo_var.get()
            quantum = int(self.quantum_var.get())
            total_frames = int(self.mem_var.get())
            page_size = int(self.page_size_var.get())
            num_proc = int(self.num_proc_var.get()) 
            if quantum <= 0 or total_frames <= 0 or num_proc <= 0 or page_size <= 0:
                raise ValueError("All parameters must be positive integers.")
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid parameter: {e}")
            return

        self.status_bar.config(text="Compiling and running simulation...")
        self.start_btn.config(state=tk.DISABLED)
        self.next_btn.config(state=tk.DISABLED)
        self.prev_btn.config(state=tk.DISABLED)
        self.update_idletasks()

        try:
            # 1. Write C file
            with open(c_file, "w", encoding="utf-8") as f:
                f.write(C_SOURCE_CODE)

            # 2. Compile
            compile_cmd = ["gcc", c_file, "-o", exe_name]
            p_compile = subprocess.run(compile_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p_compile.returncode != 0:
                 err = p_compile.stderr.decode(errors="ignore")
                 raise Exception(f"Compilation failed with error code {p_compile.returncode}. \n--- C Output ---\n{err}")

            # 3. Run executable with ALL dynamic arguments
            # Args: [exe, algo, quantum, total_frames, page_size, num_proc]
            run_cmd = [exe_name, algo, str(quantum), str(total_frames), str(page_size), str(num_proc)] if platform.system() == 'Windows' else ["./" + exe_name, algo, str(quantum), str(total_frames), str(page_size), str(num_proc)]
            
            p_run = subprocess.run(run_cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p_run.returncode != 0:
                 err = p_run.stderr.decode(errors="ignore")
                 raise Exception(f"Execution failed with error code {p_run.returncode}. \n--- C Output ---\n{err}")


            # 4. Load snapshots
            self.load_snapshots_from_file("events.log")

            # 5. Enable navigation & report
            if self.snapshot_count > 0:
                self.next_btn.config(state=tk.NORMAL)
                self.show_next_snapshot()
                self.show_final_report()
                self.status_bar.config(text=f"Loaded {self.snapshot_count} snapshots. Click Next Step ⏭ to step through the timeline.")
            else:
                messagebox.showinfo("No data", "No snapshots found in events.log. Simulation may have failed internally.")
                self.start_btn.config(state=tk.NORMAL)

        except Exception as ex:
            messagebox.showerror("Compilation/Execution Error", f"Failed to compile or run C code. \n\n{str(ex)}")
            self.start_btn.config(state=tk.NORMAL)
            self.status_bar.config(text="Compilation/execution failed.")
        finally:
            self.start_btn.config(state=tk.NORMAL)


    def load_snapshots_from_file(self, events_file):
        self.snapshots = []
        try:
            with open(events_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            obj = json.loads(line)
                            self.snapshots.append(obj)
                        except json.JSONDecodeError:
                            continue
            self.snapshot_count = len(self.snapshots)
            self.current_snapshot_index = -1
        except FileNotFoundError:
            self.snapshot_count = 0

    # -------------------- Navigation & UI Update --------------------
    def show_next_snapshot(self):
        if self.current_snapshot_index + 1 < self.snapshot_count:
            self.current_snapshot_index += 1
            self.update_ui_with_snapshot(self.snapshots[self.current_snapshot_index])
            self.prev_btn.config(state=tk.NORMAL)
        if self.current_snapshot_index + 1 >= self.snapshot_count:
            self.next_btn.config(state=tk.DISABLED)

    def show_prev_snapshot(self):
        if self.current_snapshot_index - 1 >= 0:
            self.current_snapshot_index -= 1
            self.update_ui_with_snapshot(self.snapshots[self.current_snapshot_index])
            self.next_btn.config(state=tk.NORMAL)
        if self.current_snapshot_index - 1 < 0:
            self.prev_btn.config(state=tk.DISABLED)

    def update_ui_with_snapshot(self, snapshot):
        time = snapshot.get("time", 0)
        self.step_label.config(text=f"Step: {self.current_snapshot_index + 1}/{self.snapshot_count} (Time: {time}s)")
        
        # Available resources (Gauges)
        res = snapshot.get("resources", {})
        cpu_status = res.get("cpu_status", "N/A")
        mem_avail = res.get("mem_available", 0)
        mem_max = res.get("mem_max", 5)

        # CPU Gauge (Binary Semaphore)
        cpu_value = 100 if cpu_status == "Busy" else 0
        self.cpu_gauge["value"] = cpu_value
        self.cpu_label.config(text=f"[{cpu_status}]")
        
        # Update CPU gauge color based on status
        style = ttk.Style()
        if cpu_status == "Busy":
            style.configure("TProgressbar", troughcolor="white", background="#ef4444") # Red/Busy
        else:
            style.configure("TProgressbar", troughcolor="white", background="#10b981") # Green/Available

        # Memory Gauge (Counting Frames)
        mem_allocated = mem_max - mem_avail
        mem_percent = (mem_allocated / mem_max) * 100 if mem_max > 0 else 0
        self.mem_gauge["value"] = mem_percent
        self.mem_label.config(text=f"[{mem_allocated} / {mem_max} Frames]") 
        
        # Update Memory gauge color based on usage
        if mem_percent > 80:
            style.configure("TProgressbar", troughcolor="white", background="#f97316") # Orange/High Usage
        elif mem_percent > 50:
            style.configure("TProgressbar", troughcolor="white", background="#f59e0b") # Yellow/Medium Usage
        else:
            style.configure("TProgressbar", troughcolor="white", background="#3b82f6") # Blue/Low Usage


        # Update Treeview (and calculate contention metrics)
        for row in self.tree.get_children():
            self.tree.delete(row)

        processes = snapshot.get("processes", [])
        
        # --- NEW: Calculate Contention Metrics ---
        cpu_wait_count = 0
        mem_wait_count = 0

        for i, proc in enumerate(processes):
            pid = f"P{proc.get('id', i+1)}"
            prio = proc.get('prio', 0)
            burst = proc.get('burst', '')
            remaining = proc.get('remaining', '')
            mem_needed = proc.get('mem_needed', 0)
            max_mem = proc.get('max_mem', 0)
            mem_allocated = proc.get('mem_allocated', 0)
            status = proc.get("status", "Waiting")
            values = (pid, prio, burst, remaining, mem_needed, max_mem, mem_allocated, status)
            
            tag = status
            if status == "Waiting (CPU)":
                 cpu_wait_count += 1
                 tag = "Waiting"
            elif "Waiting (Memory" in status or "Banker" in status:
                 mem_wait_count += 1
                 if "Banker" in status:
                     tag = "Banker Denied"
                 else:
                     tag = "Waiting"
            
            self.tree.insert("", tk.END, values=values, tags=(tag,))
        
        # --- NEW: Update Contention Metrics Labels ---
        self.cpu_contention_label.config(text=f"Processes Waiting for CPU: {cpu_wait_count}")
        self.mem_contention_label.config(text=f"Processes Waiting for Memory: {mem_wait_count} (Including Banker's Denial)")

        # Draw Gantt chart
        self.draw_gantt(snapshot.get("timeline", []))

        self.status_bar.config(text=f"Showing step {self.current_snapshot_index + 1} of {self.snapshot_count}. Current Time: {time}s")

    # -------------------- Gantt drawing --------------------
    def draw_gantt(self, timeline):
        c = self.gantt_canvas
        c.delete("all")
        if not timeline:
            c.create_text(10, 10, anchor="nw", text="No timeline data yet. Press Next Step ⏭.", font=("Segoe UI", 10), fill="#475569")
            return

        width = c.winfo_width() or 800
        height = c.winfo_height() or 160

        padding_left = 8
        padding_right = 8
        padding_top = 10
        padding_bottom = 20

        available_w = max(10, width - padding_left - padding_right)
        n = len(timeline)
        slot_w = available_w / max(1, n)

        color_map = {}
        for i in range(1, 51): 
            color_map[f"P{i}"] = self.process_colors[(i - 1) % len(self.process_colors)]

        # Draw bars
        for i, entry in enumerate(timeline):
            x0 = padding_left + i * slot_w
            x1 = x0 + slot_w - 2
            y0 = padding_top + 10
            y1 = height - padding_bottom
            fill = color_map.get(entry, "#9ca3af")
            c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="#0f1724")
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=entry, font=("Segoe UI", 10, "bold"), fill="#0f1724")

        # Draw axis/time markers
        for i in range(n + 1):
            x = padding_left + i * slot_w
            c.create_text(x, height - 6, text=str(i), anchor="n", font=("Segoe UI", 8), fill="#334155")
            if i > 0 and i < n:
                c.create_line(x, height - 20, x, height - 35, fill="#cbd5e1")


    # -------------------- Final report --------------------
    def show_final_report(self):
        try:
            if not os.path.exists("output.json"):
                self.report_text.config(state=tk.NORMAL)
                self.report_text.delete("1.0", tk.END)
                self.report_text.insert(tk.END, "output.json not found. Run the simulation first.")
                self.report_text.config(state=tk.DISABLED)
                return
            
            with open("output.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                
            self.report_text.config(state=tk.NORMAL)
            self.report_text.delete("1.0", tk.END)
            
            procs = data.get("processes", [])
            total_time = data.get("totalTime", 1)
            total_burst_time = data.get("totalBurstTime", 0)
            
            # 1. Performance Metrics
            cpu_utilization = (total_burst_time / total_time) * 100 if total_time > 0 else 0
            
            # 2. Formatted Report
            header = f"--- SCHEDULER: PRIORITY + {data.get('algorithm', 'N/A')} ({data.get('numProcesses', 0)} Processes) ---\n"
            header += f"{'PID':<4}{'Prio':>5}{'Burst':>8}{'MemReq':>8}{'MaxMem':>8}{'Completion':>12}{'Turnaround':>12}{'Waiting':>10}\n"
            self.report_text.insert(tk.END, header)
            self.report_text.insert(tk.END, "=" * 75 + "\n")
            
            for p in procs:
                line = f"P{p['id']:<3}{p['prio']:>5}{p['burst']:>8}{p['memNeeded']:>8}{p['maxMem']:>8}{p['completion']:>12}{p['turnaroundTime']:>12}{p['waitingTime']:>10}\n"
                self.report_text.insert(tk.END, line)
                
            # 3. Averages
            if procs:
                avg_turn = sum(p["turnaroundTime"] for p in procs) / len(procs)
                avg_wait = sum(p["waitingTime"] for p in procs) / len(procs)
                self.report_text.insert(tk.END, "\n")
                self.report_text.insert(tk.END, f"Average Turnaround Time: {avg_turn:.2f} s\n")
                self.report_text.insert(tk.END, f"Average Waiting Time:    {avg_wait:.2f} s\n")
            
            # 4. Display Metrics
            self.metrics_label.config(text=f"Metrics: CPU Util: {cpu_utilization:.2f}% | Total Time: {total_time} s | Processes Completed: {len(procs)}")
            
            self.report_text.config(state=tk.DISABLED)
            self.status_bar.config(text="Final report loaded.")
            
        except Exception as e:
            messagebox.showerror("Report Error", f"Failed to load report data: {str(e)}")
            self.status_bar.config(text="Failed to load report.")

# Entry point
if __name__ == "__main__":
    app = SemaphoreUI()
    app.mainloop()