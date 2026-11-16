<?php
// Mini-Task API — version PHP 8.3 (PHP-FPM + Nginx, port 8081).
// Point d'entrée unique : Nginx envoie toutes les requêtes à ce fichier.
declare(strict_types=1);

const JSON_FLAGS = JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES;
const MAX_N = 40;

// --- Stockage en mémoire --------------------------------------------------------
// PHP-FPM est « sans partage » : chaque requête repart de zéro. Pour ne pas
// relire tasks.json à chaque requête, et pour que les POST persistent entre
// requêtes (comme dans les trois autres versions), on utilise APCu, la mémoire
// partagée entre les processus du pool.
define('USE_APCU', function_exists('apcu_fetch') && filter_var(ini_get('apc.enabled'), FILTER_VALIDATE_BOOLEAN));

function load_tasks(): array
{
    if (USE_APCU) {
        $tasks = apcu_fetch('tasks', $hit);
        if ($hit) {
            return $tasks;
        }
    }
    $tasks = json_decode(file_get_contents(__DIR__ . '/../tasks.json'), true, 512, JSON_THROW_ON_ERROR);
    if (USE_APCU) {
        apcu_store('tasks', $tasks);
    }
    return $tasks;
}

function send(int $status, mixed $body): never
{
    $json = json_encode($body, JSON_FLAGS);
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Content-Length: ' . strlen($json));
    echo $json;
    exit;
}

function fib(int $n): int
{
    return $n < 2 ? $n : fib($n - 1) + fib($n - 2);
}

function create_task(): never
{
    try {
        $payload = json_decode(file_get_contents('php://input'), true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        send(400, ['error' => 'invalid payload']);
    }
    if (!is_array($payload) || array_is_list($payload)) {
        send(400, ['error' => 'invalid payload']);
    }

    $title = $payload['title'] ?? null;
    $priority = $payload['priority'] ?? null;
    $done = array_key_exists('done', $payload) ? $payload['done'] : false;
    if (!is_string($title) || $title === ''
        || !is_int($priority) || $priority < 1 || $priority > 5
        || !is_bool($done)) {
        send(400, ['error' => 'invalid payload']);
    }

    // Section critique : verrou simple dans APCu.
    if (USE_APCU) {
        while (!apcu_add('lock', 1, 10)) {
            usleep(200);
        }
    }
    try {
        $tasks = load_tasks();
        $task = ['id' => count($tasks) + 1, 'title' => $title, 'done' => $done, 'priority' => $priority];
        $tasks[] = $task;
        if (USE_APCU) {
            apcu_store('tasks', $tasks);
        }
    } finally {
        if (USE_APCU) {
            apcu_delete('lock');
        }
    }
    send(201, $task);
}

// --- Routage ---------------------------------------------------------------------
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($method === 'GET' && $path === '/health') {
    send(200, ['status' => 'ok']);
}

if ($path === '/tasks') {
    if ($method === 'GET') {
        send(200, load_tasks());
    }
    if ($method === 'POST') {
        create_task();
    }
}

if ($method === 'GET' && preg_match('#^/tasks/([0-9]{1,18})\z#', $path, $m) === 1) {
    $id = (int) $m[1];
    $tasks = load_tasks();
    // Les identifiants sont séquentiels (1..N) : accès direct par position.
    if ($id >= 1 && isset($tasks[$id - 1]) && $tasks[$id - 1]['id'] === $id) {
        send(200, $tasks[$id - 1]);
    }
    send(404, ['error' => 'not found']);
}

if ($method === 'GET' && $path === '/compute') {
    $raw = $_GET['n'] ?? null;
    if (!is_string($raw) || preg_match('/^[0-9]{1,18}\z/', $raw) !== 1 || (int) $raw > MAX_N) {
        send(400, ['error' => 'invalid n']);
    }
    $n = (int) $raw;
    send(200, ['n' => $n, 'result' => fib($n)]);
}

send(404, ['error' => 'not found']);
