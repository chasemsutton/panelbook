#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <winhttp.h>
#include <wchar.h>
#include <string.h>

/* The launcher exits after starting the server; the server owns its lifetime. */
static void failure(const wchar_t *message) {
    MessageBoxW(NULL, message, L"Panelbook", MB_OK | MB_ICONERROR);
}

static int append_argument(wchar_t *command, size_t capacity, const wchar_t *argument) {
    size_t used = wcslen(command);
    size_t slashes = 0;
    if (used + 3 >= capacity) return 0;
    command[used++] = L' ';
    command[used++] = L'"';
    for (const wchar_t *cursor = argument; ; ++cursor) {
        wchar_t ch = *cursor;
        if (ch == L'\\') { slashes++; continue; }
        size_t count = slashes * (ch == L'"' || ch == 0 ? 2 : 1);
        if (used + count + 3 >= capacity) return 0;
        while (count--) command[used++] = L'\\';
        slashes = 0;
        if (ch == L'"') command[used++] = L'\\';
        if (ch == 0) break;
        command[used++] = ch;
    }
    command[used++] = L'"';
    command[used] = 0;
    return 1;
}

static int server_is_running(void) {
    HINTERNET session = WinHttpOpen(L"Panelbook launcher", WINHTTP_ACCESS_TYPE_NO_PROXY,
                                    WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) return 0;
    WinHttpSetTimeouts(session, 1000, 1000, 1000, 1000);
    HINTERNET connection = WinHttpConnect(session, L"127.0.0.1", 8765, 0);
    HINTERNET request = connection ? WinHttpOpenRequest(connection, L"GET", L"/api/status", NULL,
                               WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0) : NULL;
    char response[2048] = {0};
    DWORD received = 0;
    int running = request && WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                    WINHTTP_NO_REQUEST_DATA, 0, 0, 0) && WinHttpReceiveResponse(request, NULL)
                    && WinHttpReadData(request, response, sizeof(response) - 1, &received)
                    && strstr(response, "\"version\"") && strstr(response, "\"localMode\"");
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return running;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    (void)instance; (void)previous; (void)command_line; (void)show;
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) { failure(L"Could not read the launcher arguments."); return 1; }
    int standard_launch = argc == 1;
    if (standard_launch && server_is_running()) {
        ShellExecuteW(NULL, L"open", L"http://127.0.0.1:8765/", NULL, NULL, SW_SHOWNORMAL);
        LocalFree(argv);
        return 0;
    }

    wchar_t root[MAX_PATH];
    DWORD length = GetModuleFileNameW(NULL, root, MAX_PATH);
    if (!length || length >= MAX_PATH) { failure(L"Panelbook's folder path is too long."); LocalFree(argv); return 1; }
    wchar_t *separator = wcsrchr(root, L'\\');
    if (!separator) { failure(L"Could not locate the Panelbook folder."); LocalFree(argv); return 1; }
    *separator = 0;
    wchar_t program[MAX_PATH], executable[MAX_PATH], data[MAX_PATH], stdout_path[MAX_PATH], stderr_path[MAX_PATH];
    if (swprintf_s(program, MAX_PATH, L"%s\\program", root) < 0 ||
        swprintf_s(executable, MAX_PATH, L"%s\\PanelbookServer.exe", program) < 0 ||
        swprintf_s(data, MAX_PATH, L"%s\\data", root) < 0 ||
        swprintf_s(stdout_path, MAX_PATH, L"%s\\server.stdout.log", data) < 0 ||
        swprintf_s(stderr_path, MAX_PATH, L"%s\\server.stderr.log", data) < 0) {
        failure(L"Panelbook's folder path is too long."); LocalFree(argv); return 1;
    }
    if (GetFileAttributesW(executable) == INVALID_FILE_ATTRIBUTES) {
        failure(L"program\\PanelbookServer.exe is missing. Extract the complete portable ZIP.");
        LocalFree(argv); return 1;
    }
    if (!CreateDirectoryW(data, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) {
        failure(L"Could not create Panelbook's data folder."); LocalFree(argv); return 1;
    }

    wchar_t command[32768];
    if (swprintf_s(command, 32768, L"\"%s\"", executable) < 0) {
        failure(L"Could not prepare the server command."); LocalFree(argv); return 1;
    }
    for (int i = 1; i < argc; ++i) {
        if (!append_argument(command, 32768, argv[i])) {
            failure(L"The server command is too long."); LocalFree(argv); return 1;
        }
    }
    LocalFree(argv);

    SECURITY_ATTRIBUTES security = {sizeof(security), NULL, TRUE};
    HANDLE out = CreateFileW(stdout_path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             &security, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    HANDLE err = CreateFileW(stderr_path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             &security, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE || err == INVALID_HANDLE_VALUE) {
        if (out != INVALID_HANDLE_VALUE) CloseHandle(out);
        if (err != INVALID_HANDLE_VALUE) CloseHandle(err);
        failure(L"Could not open Panelbook's server logs in the data folder."); return 1;
    }
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (input == INVALID_HANDLE_VALUE) {
        CloseHandle(out); CloseHandle(err);
        failure(L"Could not prepare Panelbook's server input."); return 1;
    }
    startup.hStdInput = input;
    startup.hStdOutput = out;
    startup.hStdError = err;
    PROCESS_INFORMATION process = {0};
    SetEnvironmentVariableW(L"PYINSTALLER_RESET_ENVIRONMENT", L"1");
    BOOL started = CreateProcessW(executable, command, NULL, NULL, TRUE,
                                  CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                                  NULL, program, &startup, &process);
    CloseHandle(out);
    CloseHandle(err);
    CloseHandle(input);
    if (!started) { failure(L"Could not start Panelbook. Check data\\server.stderr.log."); return 1; }
    if (standard_launch) {
        int ready = 0;
        for (int attempt = 0; attempt < 100; ++attempt) {
            if (server_is_running()) { ready = 1; break; }
            if (WaitForSingleObject(process.hProcess, 200) == WAIT_OBJECT_0) break;
        }
        if (!ready) {
            failure(L"Panelbook did not start. Check data\\server.stderr.log for details.");
            CloseHandle(process.hThread);
            CloseHandle(process.hProcess);
            return 1;
        }
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
