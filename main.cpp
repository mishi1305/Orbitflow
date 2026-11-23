#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <iomanip>
#include <numeric>
#include <fstream>
#include <sstream>
#include <cstdlib>
using namespace std;

struct Task {
    int id;
    string region;
    string route;
    int arrival, burst, priority, resources;

    int start = -1;
    int completion = 0;
    int waiting = 0;
    int turnaround = 0;
    int response = -1;
};

class OrbitFlow {
private:
    vector<Task> tasks;
    int nextID = 1;
    int totalResources = 5;

    // Reload persisted tasks from MySQL through Python bridge.
    void loadFromDatabase() {
        int rc = system("py db_bridge.py load");
        if (rc != 0) {
            cout << "\nWarning: Could not load tasks from MySQL. "
                 << "Check db_config.py and database connection.\n";
            return;
        }

        ifstream in("orbitflow_tasks.tsv");
        if (!in) return;

        vector<Task> loaded;
        string line;

        while (getline(in, line)) {
            if (line.empty()) continue;

            stringstream ss(line);
            string id, region, route, arrival, burst, priority, resources;

            if (!getline(ss, id, '\t') ||
                !getline(ss, region, '\t') ||
                !getline(ss, route, '\t') ||
                !getline(ss, arrival, '\t') ||
                !getline(ss, burst, '\t') ||
                !getline(ss, priority, '\t') ||
                !getline(ss, resources, '\t'))
                continue;

            Task t;

            try {
                t.id = stoi(id);
                t.region = region;
                t.route = route;
                t.arrival = stoi(arrival);
                t.burst = stoi(burst);
                t.priority = stoi(priority);
                t.resources = stoi(resources);
            }
            catch (...) {
                continue;
            }

            loaded.push_back(t);
        }

        tasks.swap(loaded);
        nextID = 1;

        for (const Task& t : tasks)
            nextID = max(nextID, t.id + 1);
    }

    void printResults(const vector<Task>& result,
                     const string& algorithm) {
        if (result.empty()) {
            cout << "\nNo tasks available.\n";
            return;
        }

        double tw = 0, tt = 0, tr = 0;

        cout << "\n========== " << algorithm
             << " RESULTS ==========\n\n";

        cout << left
             << setw(6)  << "ID"
             << setw(18) << "Region"
             << setw(9)  << "Arrival"
             << setw(8)  << "Burst"
             << setw(9)  << "Start"
             << setw(11) << "Complete"
             << setw(10) << "Waiting"
             << setw(12) << "Turnaround"
             << setw(10) << "Response" << '\n';

        cout << string(93, '-') << '\n';

        for (const Task& t : result) {
            cout << left
                 << setw(6)  << t.id
                 << setw(18) << t.region
                 << setw(9)  << t.arrival
                 << setw(8)  << t.burst
                 << setw(9)  << t.start
                 << setw(11) << t.completion
                 << setw(10) << t.waiting
                 << setw(12) << t.turnaround
                 << setw(10) << t.response << '\n';

            tw += t.waiting;
            tt += t.turnaround;
            tr += t.response;
        }

        cout << string(93, '-') << '\n';
        cout << fixed << setprecision(2);

        cout << "Average Waiting Time    : "
             << tw / result.size() << '\n';

        cout << "Average Turnaround Time : "
             << tt / result.size() << '\n';

        cout << "Average Response Time   : "
             << tr / result.size() << '\n';
    }

    vector<Task> schedule(string mode, int quantum = 2) {
        vector<Task> pending = tasks;
        vector<Task> result;

        if (pending.empty()) {
            cout << "\nPlease add tasks first.\n";
            return result;
        }

        if (mode == "FCFS" || mode == "SJF" ||
            mode == "PRIORITY") {

            int time = 0;

            while (!pending.empty()) {
                int selected = -1;

                for (int i = 0; i < (int)pending.size(); i++) {
                    if (pending[i].arrival > time)
                        continue;

                    if (selected == -1) {
                        selected = i;
                        continue;
                    }

                    bool better = false;

                    if (mode == "FCFS") {
                        better = pending[i].arrival <
                                 pending[selected].arrival;
                    }
                    else if (mode == "SJF") {
                        better = pending[i].burst <
                                 pending[selected].burst;
                    }
                    else {
                        better = pending[i].priority <
                                 pending[selected].priority;
                    }

                    if (better ||
                        ((!better) &&
                         pending[i].arrival ==
                             pending[selected].arrival &&
                         pending[i].id < pending[selected].id)) {
                        selected = i;
                    }
                }

                if (selected == -1) {
                    int nextArrival = pending[0].arrival;

                    for (const Task& t : pending)
                        nextArrival = min(nextArrival, t.arrival);

                    time = max(time, nextArrival);
                    continue;
                }

                Task t = pending[selected];
                pending.erase(pending.begin() + selected);

                t.start = time;
                t.response = t.start - t.arrival;
                t.waiting = t.start - t.arrival;
                t.completion = time + t.burst;
                t.turnaround = t.completion - t.arrival;

                time = t.completion;
                result.push_back(t);
            }
        }
        else if (mode == "RR") {
            // Round Robin scheduling
            const int n = static_cast<int>(pending.size());

            if (quantum <= 0) {
                cout << "\nTime quantum must be positive.\n";
                return result;
            }

            vector<int> remaining;
            remaining.reserve(n);

            for (const Task& t : pending)
                remaining.push_back(t.burst);

            vector<int> firstStart(n, -1);
            vector<int> completion(n, 0);
            vector<int> order(n);

            iota(order.begin(), order.end(), 0);

            sort(order.begin(), order.end(),
                 [&](int a, int b) {
                     if (pending[a].arrival == pending[b].arrival)
                         return pending[a].id < pending[b].id;

                     return pending[a].arrival < pending[b].arrival;
                 });

            vector<int> ready;
            int time = 0;
            int finished = 0;
            int next = 0;

            while (finished < n) {
                // Add arrived tasks to ready queue.
                while (next < n &&
                       pending[order[next]].arrival <= time) {
                    ready.push_back(order[next]);
                    ++next;
                }

                // If queue is empty, jump to next arrival.
                if (ready.empty()) {
                    if (next < n) {
                        time = max(time, pending[order[next]].arrival);
                        continue;
                    }
                    break;
                }

                int idx = ready.front();
                ready.erase(ready.begin());

                if (firstStart[idx] == -1)
                    firstStart[idx] = time;

                int runTime = min(quantum, remaining[idx]);

                time += runTime;
                remaining[idx] -= runTime;

                // Add new arrivals before requeueing current task.
                while (next < n &&
                       pending[order[next]].arrival <= time) {
                    ready.push_back(order[next]);
                    ++next;
                }

                if (remaining[idx] > 0) {
                    ready.push_back(idx);
                }
                else {
                    completion[idx] = time;
                    ++finished;
                }
            }

            for (int i = 0; i < n; ++i) {
                Task t = pending[i];

                t.start = firstStart[i];
                t.response = t.start - t.arrival;
                t.completion = completion[i];
                t.turnaround = t.completion - t.arrival;
                t.waiting = t.turnaround - t.burst;

                result.push_back(t);
            }

            sort(result.begin(), result.end(),
                 [](const Task& a, const Task& b) {
                     if (a.start == b.start)
                         return a.id < b.id;

                     return a.start < b.start;
                 });
        }

        return result;
    }

public:
    OrbitFlow() {
        loadFromDatabase();
    }

    void addTask() {
        Task t;
        t.id = nextID++;

        cout << "\nRegion name (type without spaces, e.g. FloodZoneA): ";
        cin >> t.region;

        cout << "Active route name (type without spaces, e.g. RouteAlpha): ";
        cin >> t.route;

        cout << "Arrival time: ";
        cin >> t.arrival;

        cout << "Burst time: ";
        cin >> t.burst;

        cout << "Priority (1 = highest): ";
        cin >> t.priority;

        cout << "Required resource units: ";
        cin >> t.resources;

        if (t.arrival < 0 || t.burst <= 0 ||
            t.priority <= 0 || t.resources < 0) {
            cout << "\nInvalid values. Task not added.\n";
            nextID--;
            return;
        }

        // Save to MySQL using Python bridge.
        string cmd = "py db_bridge.py add " + t.region + " " +
                     t.route + " " +
                     to_string(t.arrival) + " " +
                     to_string(t.burst) + " " +
                     to_string(t.priority) + " " +
                     to_string(t.resources);

        int rc = system(cmd.c_str());

        if (rc != 0) {
            cout << "\nTask was NOT saved to MySQL. Check db_config.py, "
                 << "and enter region/route names that exist in the database.\n";
            return;
        }

        loadFromDatabase();
        cout << "\nTask saved to MySQL successfully.\n";
    }

    void displayTasks() {
        if (tasks.empty()) {
            cout << "\nNo tasks available.\n";
            return;
        }

        cout << "\n========== IMAGING TASKS ==========\n";

        cout << left
             << setw(6)  << "ID"
             << setw(12) << "Region"
             << setw(12) << "Route"
             << setw(9)  << "Arrival"
             << setw(8)  << "Burst"
             << setw(10) << "Priority"
             << setw(10) << "Resources" << '\n';

        cout << string(67, '-') << '\n';

        for (const Task& t : tasks) {
            cout << left
                 << setw(6)  << t.id
                 << setw(12) << t.region
                 << setw(12) << t.route
                 << setw(9)  << t.arrival
                 << setw(8)  << t.burst
                 << setw(10) << t.priority
                 << setw(10) << t.resources << '\n';
        }
    }

    void simulationInfo() {
        cout << "\n===== SATELLITE SIMULATION =====\n";
        cout << "Satellite: ORBIT-01 (simulated)\n";
        cout << "Active routes: ROUTE-A, ROUTE-B, ROUTE-C\n";
        cout << "Regions: Flood, City, Forest, Rural\n";
        cout << "These are predefined simulation examples.\n";
    }

    void runScheduling() {
        cout << "\n1. FCFS\n";
        cout << "2. SJF (Non-preemptive)\n";
        cout << "3. Priority (Non-preemptive)\n";
        cout << "4. Round Robin\n";
        cout << "Choose algorithm: ";

        int choice;

        if (!(cin >> choice)) {
            cin.clear();
            cin.ignore(10000, '\n');
            cout << "Invalid input.\n";
            return;
        }

        string mode;

        switch (choice) {
            case 1: mode = "FCFS"; break;
            case 2: mode = "SJF"; break;
            case 3: mode = "PRIORITY"; break;
            case 4: mode = "RR"; break;

            default:
                cout << "Invalid algorithm choice.\n";
                return;
        }

        int quantum = 2;

        if (mode == "RR") {
            cout << "Enter time quantum (positive integer): ";

            if (!(cin >> quantum) || quantum <= 0) {
                cin.clear();
                cin.ignore(10000, '\n');
                cout << "Invalid time quantum.\n";
                return;
            }
        }

        vector<Task> result = schedule(mode, quantum);
        printResults(result, mode);
    }

    void compareAlgorithms() {
        if (tasks.empty()) {
            cout << "\nAdd tasks first.\n";
            return;
        }

        cout << "\n======= ALGORITHM COMPARISON =======\n";

        cout << left
             << setw(14) << "Algorithm"
             << setw(20) << "Avg Waiting"
             << setw(22) << "Avg Turnaround"
             << setw(18) << "Avg Response" << '\n';

        cout << string(74, '-') << '\n';

        vector<string> modes = {
            "FCFS", "SJF", "PRIORITY", "RR"
        };

        for (const string& mode : modes) {
            vector<Task> r = schedule(mode, 2);

            double w = 0, t = 0, resp = 0;

            for (const Task& task : r) {
                w += task.waiting;
                t += task.turnaround;
                resp += task.response;
            }

            if (r.empty()) {
                cout << left << setw(14) << mode
                     << setw(20) << "N/A"
                     << setw(22) << "N/A"
                     << setw(18) << "N/A" << '\n';
                continue;
            }

            cout << fixed << setprecision(2) << left
                 << setw(14) << mode
                 << setw(20) << w / r.size()
                 << setw(22) << t / r.size()
                 << setw(18) << resp / r.size() << '\n';
        }

        cout << "\nRound Robin comparison uses quantum = 2.\n";
    }

    // -------- RESOURCE SIMULATION --------
    void resourceSimulation() {
        cout << "\n===== RESOURCE MANAGEMENT =====\n";
        cout << "Total available resource units: "
             << totalResources << '\n';

        if (tasks.empty()) {
            cout << "Add tasks first.\n";
            return;
        }

        int available = totalResources;
        int blocked = 0;

        cout << "\nTask\tRequired\tStatus\n";
        cout << string(40, '-') << '\n';

        for (const Task& t : tasks) {
            cout << t.id << "\t" << t.resources << "\t\t";

            if (t.resources <= available) {
                available -= t.resources;
                cout << "Allocated in this demo\n";
            }
            else {
                blocked++;
                cout << "Waiting - insufficient resources\n";
            }
        }

        cout << "\nUnallocated resource units: "
             << available << '\n';

        cout << "Tasks waiting for resources: "
             << blocked << '\n';

        if (blocked > 0) {
            cout << "Resource contention detected.\n";
            cout << "This is not by itself proof of deadlock.\n";
        }
        else {
            cout << "No resource requests blocked in this demo.\n";
        }

        cout << "\nNote: This is a basic allocation simulation, "
             << "not a full deadlock detection algorithm.\n";
    }

    // -------- DEADLOCK DETECTION DEMO --------
    void deadlockDemo() {
        cout << "\n===== MULTI-RESOURCE DEADLOCK DETECTION =====\n";

        // Illustrative resource capacities.
        const int total[4] = {4, 8, 100, 1};
        const string names[4] = {
            "CPU", "RAM", "Storage", "Imager"
        };

        cout << "\nResource Capacities:\n";

        for (int i = 0; i < 4; i++)
            cout << names[i] << ": " << total[i] << '\n';

        // Sample task allocations.
        int allocation[3][4] = {
            {1, 2, 10, 0},
            {1, 2, 20, 0},
            {1, 1, 10, 0}
        };

        // Additional resource requests.
        int request[3][4] = {
            {1, 2, 10, 1},
            {1, 1, 10, 0},
            {1, 2, 10, 1}
        };

        // Calculate available resources.
        int available[4];

        for (int j = 0; j < 4; j++) {
            int used = 0;

            for (int i = 0; i < 3; i++)
                used += allocation[i][j];

            available[j] = total[j] - used;
        }

        bool finish[3] = {false, false, false};

        cout << "\nAvailable resources initially:\n";

        for (int j = 0; j < 4; j++)
            cout << names[j] << ": " << available[j] << '\n';

        // Deadlock detection algorithm.
        bool progress = true;

        while (progress) {
            progress = false;

            for (int i = 0; i < 3; i++) {
                if (finish[i]) continue;

                bool possible = true;

                for (int j = 0; j < 4; j++) {
                    if (request[i][j] > available[j]) {
                        possible = false;
                        break;
                    }
                }

                if (possible) {
                    for (int j = 0; j < 4; j++)
                        available[j] += allocation[i][j];

                    finish[i] = true;
                    progress = true;

                    cout << "\nTask T" << i + 1
                         << " can finish; resources released.";
                }
            }
        }

        cout << "\n\n===== DETECTION RESULT =====\n";

        bool deadlock = false;

        for (int i = 0; i < 3; i++) {
            if (!finish[i]) {
                cout << "T" << i + 1 << " is blocked.\n";
                deadlock = true;
            }
        }

        if (deadlock)
            cout << "\nDeadlock detected (simulation).\n";
        else
            cout << "\nNo deadlock detected.\n";
    }
};

int main() {
    OrbitFlow app;
    int choice;

    do {
        cout << "\n========================================\n";
        cout << "       ORBITFLOW SATELLITE SIMULATOR\n";
        cout << "========================================\n";

        cout << "1. Add Imaging Task\n";
        cout << "2. Display All Tasks\n";
        cout << "3. Satellite, Routes and Regions\n";
        cout << "4. Run Scheduling Algorithm\n";
        cout << "5. Compare All Algorithms\n";
        cout << "6. Resource Allocation Simulation\n";
        cout << "7. View Satellite Images\n";
        cout << "8. Exit\n";
        cout << "9. Deadlock Detection Demo\n";

        cout << "Enter choice: ";

        if (!(cin >> choice)) {
            cin.clear();
            cin.ignore(10000, '\n');
            cout << "Invalid input. Enter a number.\n";
            continue;
        }

        switch (choice) {
            case 1:
                app.addTask();
                break;

            case 2:
                app.displayTasks();
                break;

            case 3:
                app.simulationInfo();
                break;

            case 4:
                app.runScheduling();
                break;

            case 5:
                app.compareAlgorithms();
                break;

            case 6:
                app.resourceSimulation();
                break;

            case 7:
                cout << "\nOpening Satellite Image Viewer...\n";
                system("python view_satellite.py");
                break;

            case 8:
                cout << "\nExiting OrbitFlow. Goodbye!\n";
                break;

            case 9:
                app.deadlockDemo();
                break;

            default:
                cout << "\nInvalid choice. Try again.\n";
        }

    } while (choice != 8);

    return 0;
}