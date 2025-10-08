# Dynamic OS Resource Allocator (Semaphore-Based Heap Management System)

This project is a simulation of **dynamic resource allocation and synchronization** in an operating system using **C** and **Python (Tkinter)**.  
It demonstrates **process scheduling**, **CPU & Memory semaphores**, and **real-time visualization** of resource management.

---

## 🧩 Overview

This system integrates:
- A **C-based backend** implementing semaphore-controlled CPU & memory management.
- A **Python GUI (Tkinter)** frontend that compiles, runs, and visualizes the simulation.
- A **logging system** that records process states, memory allocation, CPU usage, and execution timeline in JSON.

---

## 🧠 Features

- Implements **Binary (CPU)** and **Counting (Memory)** semaphores.
- Supports both **Round Robin (RR)** and **First-Come-First-Serve (FCFS)** scheduling.
- Dynamically allocates and deallocates memory blocks per process.
- Tracks **starvation**, **critical sections**, and **preemption**.
- Produces **live visualizations** of:
  - Process states
  - Resource utilization
  - Gantt chart timeline
- Generates detailed **event logs (`events.log`)** and **final performance reports (`output.json`)**.
- Detects and prevents **resource contention** using smart semaphore control.

---

## ⚙️ Algorithms Implemented

- **Round Robin Scheduling (RR)**
- **First Come First Serve (FCFS)**
- **Semaphore-based Resource Allocation**
- **Starvation Detection**
- **Memory Allocation & Deallocation**

---

## 🧰 Compilation

> The Python GUI automatically compiles and executes the embedded C code,  
> but you can also compile it manually if needed.

### 🪟 Windows
```bash
gcc semaphore_simulator.c -o semaphore_simulator.exe
