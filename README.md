# OrbitFlow 🛰️
### Satellite Earth Imaging Task Scheduler and Resource Management Simulator

OrbitFlow is a simulation-based project that combines Operating System (OS) scheduling concepts and Database Management System (DBMS) functionalities to manage satellite Earth-imaging tasks.

The system allows users to create imaging tasks, schedule them using different algorithms, analyse scheduling performance, manage simulated resources, explore satellite datasets, and visualize project information through a web-based dashboard.

---

## 📌 Project Overview

Satellite imaging requests may vary in priority, arrival time, processing duration, and resource requirements. Efficient scheduling and resource management are important for organizing these requests.

OrbitFlow provides a simulated environment for managing such tasks and studying the behaviour of different scheduling algorithms.

The project demonstrates the practical implementation of OS and DBMS concepts through task scheduling, resource management, database operations, image visualization, and an interactive dashboard.

> **Note:** OrbitFlow is an educational simulation. It does not control real satellites, use live satellite telemetry, or perform real-time disaster detection.

---

## 🎯 Objectives

- Simulate satellite Earth-imaging task management.
- Implement and compare CPU scheduling algorithms.
- Calculate scheduling performance metrics.
- Simulate resource allocation and deadlock scenarios.
- Store and manage project data using MySQL.
- Visualize satellite, route, region, and dataset information.
- Integrate backend functionality with a web-based dashboard.

---

## ✨ Features

### 1. Command Center
Provides a centralized dashboard for viewing project information and navigating between different modules.

### 2. Imaging Task Management
Create and manage imaging tasks with attributes such as:

- Task ID and task name
- Region
- Satellite assignment
- Arrival time
- Burst time
- Priority
- Resource requirements
- Task status

### 3. Process Scheduling

OrbitFlow supports the following scheduling algorithms:

| Algorithm | Description |
|---|---|
| FCFS (First Come, First Served) | Executes tasks in arrival order. |
| SJF (Shortest Job First) | Selects tasks based on shortest burst time. |
| Priority Scheduling | Schedules tasks according to priority. |
| Round Robin | Allocates CPU time using a configurable time quantum. |

### 4. Scheduling Performance Analysis

The system calculates and visualizes scheduling metrics, including:

- Waiting Time
- Turnaround Time
- Response Time
- Completion Time

It also provides scheduling order visualization through Gantt charts and algorithm comparison charts.

### 5. Live Processing Simulation

Provides a simulation of task processing and execution progress within the system.

### 6. Resource Management

Simulates resource availability, allocation, and usage for imaging tasks.

### 7. Deadlock Simulation

Demonstrates deadlock-related scenarios through a controlled resource allocation simulation.

### 8. Satellite & Routes Visualization

Displays satellite assignments, routes, and region-related information through dashboard visualizations.

### 9. Dataset Gallery

Organizes and displays dataset images and image categories with preview functionality.

### 10. Image-Based Priority Suggestion

Suggests task priority based on the selected dataset image category. The suggested priority can be manually adjusted.

This feature uses category-based rules and is not an AI image recognition system.

### 11. Activity Logs

Displays recorded project activities for monitoring system operations.

---

## 🖥️ Technology Stack

| Technology | Purpose |
|---|---|
| C++ | Task management and OS concepts |
| Python | Backend logic, utilities, scheduling and integration |
| FastAPI | Web backend and API endpoints |
| MySQL | Relational database and persistent storage |
| HTML | Dashboard structure |
| CSS | Dashboard styling |
| JavaScript | Frontend interactions and dynamic functionality |
| Visual Studio Code | Development environment |
| MySQL Workbench | Database management |
| Git & GitHub | Version control and source code management |

---

## 🗄️ Database

OrbitFlow uses MySQL for storing and managing application records.

Major database tables include:

- `satellites`
- `routes`
- `regions`
- `imaging_tasks`
- `resource_logs`
- `scheduling_logs`
- `dataset_images`
- `activity_log`

The database supports task management, satellite and route information, scheduling records, resource logs, and dataset image metadata.

---

## 🛰️ Dataset Sources

OrbitFlow includes a dataset gallery for satellite, radar, flood-related, fire-related, and aerial traffic imagery categories.

### DLR-MVDA
DLR Multi-class Vehicle Detection and Orientation in Aerial Imagery.

Source: German Aerospace Center (DLR)

https://www.dlr.de/

### Copernicus Emergency Management Service (CEMS)
Provides emergency mapping information and products related to natural and human-made disasters.

https://emergency.copernicus.eu/

### SpaceNet 8
Flood Detection dataset focusing on flooded roads and buildings.

https://spacenet.ai/sn8-challenge/

### Sen1Floods11
A georeferenced flood dataset based on Sentinel-1 and Sentinel-2 imagery.

https://github.com/cloudtostreet/Sen1Floods11

> Dataset references may include background resources. Only images actually imported into the application's gallery are treated as integrated project data.

---

## 🏗️ System Architecture

OrbitFlow follows a modular architecture consisting of:

1. **Frontend:** HTML, CSS and JavaScript dashboard.
2. **Backend:** Python application using FastAPI.
3. **Simulation Logic:** Task scheduling, resource management, and simulation modules.
4. **Database:** MySQL for persistent records.
5. **C++ Application:** Task management and scheduling implementation.

The frontend communicates with the backend through API endpoints. Backend modules handle simulation operations and database interactions.

---

## 📂 Project Modules

| Module | Description |
|---|---|
| Command Center | Central dashboard and system overview |
| Imaging Tasks | Task creation and management |
| Process Scheduling | Scheduling algorithms and performance metrics |
| Live Processing | Task processing simulation |
| Resource Management | Resource monitoring and allocation simulation |
| Deadlock Simulation | Controlled deadlock scenario |
| Satellite & Routes | Satellite, route, and region visualization |
| Dataset Gallery | Image categories and image previews |
| Activity Logs | Recorded system activities |

---

## ⚙️ Installation & Setup

### Prerequisites

Install the following software:

- Python 3
- MySQL Server
- MySQL Workbench (optional, for database management)
- C++ compiler (if running the C++ application)
- Visual Studio Code (recommended)

### 1. Clone the repository

```bash
git clone https://github.com/mishi1305/Orbitflow.git
```

### 2. Navigate to the project directory

```bash
cd OrbitFlow
```

### 3. Install Python dependencies

Install the packages required by the project.

```bash
pip install fastapi uvicorn mysql-connector-python
```

Install any additional packages required by the project's Python modules.

### 4. Configure MySQL

- Start the MySQL server.
- Create or configure the `orbitflow` database.
- Ensure the database tables are available.
- Update database connection settings in the project's configuration file.

Do not upload database passwords or private credentials to GitHub.

### 5. Run the Dashboard

Start the FastAPI server from the project directory:

```bash
py -m uvicorn dashboard:app --port 8001
```

If `dashboard.py` is located in a different directory, specify the appropriate application directory using `--app-dir`.

### 6. Open the Dashboard

Visit the following address in your browser:

http://127.0.0.1:8001

---

## 📊 Scheduling Metrics

OrbitFlow uses the following metrics to evaluate scheduling algorithms.

### Waiting Time
The time a task spends waiting before execution.

### Turnaround Time
The total time from task arrival to task completion.

### Response Time
The time between task arrival and its first execution.

### Completion Time
The time at which a task finishes execution.

These metrics are used to compare the behaviour of FCFS, SJF, Priority Scheduling, and Round Robin.

---

## 🎓 PBL Concepts Demonstrated

### Operating Systems

- CPU scheduling
- FCFS
- Shortest Job First
- Priority Scheduling
- Round Robin
- Scheduling performance metrics
- Resource allocation
- Deadlock simulation

### Database Management Systems

- Relational database design
- Tables and relationships
- Primary keys and foreign keys
- SQL operations
- Persistent data storage
- Database connectivity

### Software Development

- Modular programming
- C++ application development
- Python backend development
- API integration
- Frontend-backend communication
- Database integration

---

## ⚠️ Limitations

- The project operates in a simulated environment.
- Satellite task execution does not control actual satellites.
- Satellite positions and orbital visualizations are conceptual.
- Resource allocation and deadlock handling are simulated.
- Priority suggestions are based on image categories and predefined rules.
- The system does not perform autonomous AI-based image classification.
- The dashboard does not process live satellite telemetry.

---

## 🚀 Future Scope

Potential future enhancements include:

- More advanced scheduling algorithms.
- Improved resource optimization strategies.
- Expanded satellite and route simulation.
- Additional satellite imagery datasets.
- Enhanced task prioritization logic.
- More realistic simulation constraints.
- Advanced data visualization and analytics.

---

## 👥 Team Astro

**Project:** OrbitFlow  
**Team ID:** OSDBMS-V-2026-T200  
**Sections:** ML-2, E, G  
**Semester:** 5th Semester

| Team Member | Student ID |
|---|---|
| Mishika Singh Nayal | 24022118 |
| Shivanki Singhal | 24022884 |
| Daksh Raj | 240111463 |

**Mentor:** Dr. Sarvesh Vishwakarma  
**Mentor Interactions:** 5

Department of Computer Science & Engineering  
Graphic Era (Deemed to be University), Dehradun

---

## 📖 References

- Python: https://docs.python.org/
- FastAPI: https://fastapi.tiangolo.com/
- MySQL: https://dev.mysql.com/doc/
- C++ Reference: https://en.cppreference.com/
- DLR-MVDA: https://www.dlr.de/
- Copernicus Emergency Management Service: https://emergency.copernicus.eu/
- SpaceNet 8: https://spacenet.ai/sn8-challenge/
- Sen1Floods11: https://github.com/cloudtostreet/Sen1Floods11/

---

## 📜 License

This project was developed for academic and educational purposes as part of the 5th Semester Project-Based Learning (PBL) coursework.
