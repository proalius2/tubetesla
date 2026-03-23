# app.py
import asyncio
import io
import base64
import cv2
import yt_dlp
import numpy as np
import httpx
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import threading
import queue

app = FastAPI()

# Almacén temporal de URLs de audio por sesión (evita pasar URLs de YouTube por el cliente)
audio_sessions = {}

# Middleware para log de todas las requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    if '/proxy-audio' in request.url.path:
        print(f"[MIDDLEWARE] Request a /proxy-audio: {request.url}")
    response = await call_next(request)
    return response

# Montar archivos estáticos para servir la imagen de fondo
app.mount("/static", StaticFiles(directory="."), name="static")

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teslatube para el Tesla de Al</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0.7)), url('/static/tesla-roadster.jpg');
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            background: linear-gradient(45deg, #ff006e, #8338ec);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 2.5em;
        }
        .controls {
            background: rgba(255,255,255,0.05);
            padding: 25px;
            border-radius: 15px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #b8b8d1;
            font-weight: 500;
        }
        input[type="text"], input[type="number"], select {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 8px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 16px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        input[type="range"] {
            width: 100%;
            margin-top: 10px;
        }
        .range-value {
            text-align: right;
            color: #ff006e;
            font-weight: bold;
        }
        .row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .row-buttons {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }
        .row-buttons .form-group {
            flex: 0 0 auto;
            margin-bottom: 0;
        }
        .buttons-row {
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }
        button {
            padding: 15px;
            background: linear-gradient(45deg, #ff006e, #8338ec);
            border: none;
            border-radius: 8px;
            color: white;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 150px;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(131, 56, 236, 0.4);
        }
        button:disabled {
            background: #444;
            cursor: not-allowed;
            transform: none;
        }
        .stats {
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .stat-box {
            background: rgba(255,255,255,0.05);
            padding: 15px 25px;
            border-radius: 10px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #ff006e;
        }
        .stat-label {
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
        }
        #stream-container {
            text-align: center;
            background: #000;
            border-radius: 15px;
            overflow: hidden;
            border: 2px solid rgba(255,255,255,0.1);
            min-height: 400px;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }
        #frame-display {
            max-width: 100%;
            max-height: 80vh;
            display: none;
        }
        #stream-container:fullscreen {
            display: flex;
            align-items: center;
            justify-content: center;
            background: #000;
            width: 100vw;
            height: 100vh;
        }
        #stream-container:fullscreen #frame-display {
            max-width: 100vw;
            max-height: 100vh;
            width: auto;
            height: auto;
        }
        #placeholder {
            color: #666;
            font-size: 18px;
        }
        .loading {
            display: none;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 3px solid rgba(255,255,255,0.1);
            border-top-color: #ff006e;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .error {
            background: rgba(255,0,0,0.2);
            border: 1px solid #ff006e;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }
        .favorites-panel {
            position: fixed;
            right: 20px;
            top: 20px;
            width: 500px;
            background: rgba(0,0,0,0.95);
            border: 3px solid #ff006e;
            border-radius: 12px;
            padding: 20px;
            z-index: 999;
            max-height: 85vh;
            overflow-y: auto;
            transition: all 0.3s ease;
            box-shadow: 0 0 20px rgba(255, 0, 110, 0.3);
        }
        .favorites-panel.collapsed {
            width: 60px;
            height: 60px;
            padding: 10px;
        }
        .favorites-panel.collapsed .panel-content {
            display: none !important;
        }
        .favorites-panel.collapsed .panel-header {
            border-bottom: none;
            margin: 0;
            padding: 0;
            justify-content: center;
        }
        .favorites-panel.collapsed .panel-header h3 {
            display: none;
        }
        .favorites-panel.collapsed .toggle-btn {
            width: 100%;
            height: 100%;
            padding: 0;
            font-size: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
        }
        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 12px;
            border-bottom: 2px solid rgba(255,0,110,0.3);
        }
        .panel-header h3 {
            color: #ff006e;
            margin: 0;
            font-size: 18px;
            font-weight: bold;
        }
        .toggle-btn {
            background: #ff006e;
            border: none;
            color: white;
            padding: 10px 15px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            transition: all 0.2s;
            min-width: 50px;
        }
        .toggle-btn:hover {
            background: #ff4d7a;
            transform: scale(1.1);
        }
        .add-favorite {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        .add-favorite input {
            flex: 1;
            padding: 10px;
            font-size: 13px;
            border-radius: 6px;
        }
        .add-favorite button {
            padding: 10px 15px;
            width: auto;
            font-size: 13px;
            font-weight: bold;
            background: linear-gradient(45deg, #00b4d8, #0077b6) !important;
            border-radius: 6px;
        }
        .add-favorite button:hover {
            transform: translateY(-2px);
        }
        .favorites-list {
            max-height: 600px;
            overflow-y: auto;
        }
        .favorite-item {
            background: rgba(255,255,255,0.05);
            padding: 12px;
            margin-bottom: 12px;
            border-radius: 6px;
            border: 1px solid rgba(255,0,110,0.3);
            font-size: 13px;
            word-break: break-all;
        }
        .favorite-item-title {
            color: #ff006e;
            font-weight: bold;
            margin-bottom: 6px;
            font-size: 14px;
        }
        .favorite-item-url {
            color: #aaa;
            font-size: 12px;
            margin-bottom: 10px;
            font-family: monospace;
        }
        .favorite-item-buttons {
            display: flex;
            gap: 6px;
        }
        .favorite-item-buttons button {
            flex: 1;
            padding: 8px 10px;
            font-size: 12px;
            margin: 0 !important;
            width: auto;
            border-radius: 5px;
            border: none;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s;
        }
        .favorite-item-buttons .load-btn {
            background: linear-gradient(45deg, #ff006e, #8338ec);
            color: white;
        }
        .favorite-item-buttons .load-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 15px rgba(255, 0, 110, 0.3);
        }
        .favorite-item-buttons .delete-btn {
            background: #ff4444;
            color: white;
        }
        .favorite-item-buttons .delete-btn:hover {
            transform: translateY(-1px);
            background: #ff6666;
        }
        .no-favorites {
            text-align: center;
            color: #666;
            padding: 30px 10px;
            font-size: 13px;
        }
        .search-panel {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            transition: all 0.3s ease;
        }
        .search-panel.hidden {
            display: none;
        }
        .search-input-group {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        .search-input-group input {
            flex: 1;
            padding: 12px;
            border: none;
            border-radius: 8px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 14px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .search-btn {
            background: linear-gradient(45deg, #00b4d8, #0077b6);
            border: none;
            border-radius: 8px;
            color: white;
            padding: 12px 20px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .search-btn:hover {
            transform: translateY(-2px);
        }
        .search-results {
            max-height: 500px;
            overflow-y: auto;
            display: none;
        }
        .search-results.active {
            display: block;
        }
        .search-result-item {
            display: flex;
            gap: 15px;
            padding: 15px;
            margin-bottom: 10px;
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.1);
            transition: all 0.2s;
        }
        .search-result-item:hover {
            background: rgba(255,255,255,0.1);
            border-color: #ff006e;
        }
        .search-result-thumb {
            width: 160px;
            height: 90px;
            object-fit: cover;
            border-radius: 6px;
            background: #333;
        }
        .search-result-info {
            flex: 1;
            min-width: 0;
        }
        .search-result-title {
            color: #fff;
            font-weight: bold;
            margin-bottom: 8px;
            font-size: 14px;
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .search-result-meta {
            color: #888;
            font-size: 12px;
            margin-bottom: 10px;
        }
        .search-result-play-btn {
            background: linear-gradient(45deg, #ff006e, #8338ec);
            border: none;
            border-radius: 6px;
            color: white;
            padding: 8px 15px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .search-result-play-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255, 0, 110, 0.3);
        }
        .search-loading {
            text-align: center;
            padding: 20px;
            color: #ff006e;
            display: none;
        }
        .search-loading.active {
            display: block;
        }
        .search-loading .spinner {
            width: 30px;
            height: 30px;
            border: 2px solid rgba(255,255,255,0.1);
            border-top-color: #ff006e;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }
        .search-error {
            background: rgba(255,0,0,0.2);
            border: 1px solid #ff4444;
            padding: 15px;
            border-radius: 8px;
            color: #ff6666;
            font-size: 13px;
            display: none;
            text-align: center;
        }
        .search-error.active {
            display: block;
        }
        .search-error.success {
            background: rgba(46, 204, 113, 0.2);
            border: 1px solid #2ecc71;
            color: #2ecc71;
        }
        .no-results {
            text-align: center;
            color: #666;
            padding: 30px;
            font-size: 13px;
            display: none;
        }
        .no-results.active {
            display: block;
        }
        .search-result-buttons {
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }
        .search-result-fav-btn {
            background: linear-gradient(45deg, #ffd700, #ffb347);
            border: none;
            border-radius: 6px;
            color: #333;
            padding: 8px 15px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
            flex: 1;
        }
        .search-result-fav-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255, 215, 0, 0.3);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 Teslatube - Tesla de Al</h1>
        
        <div class="stats">
            <div class="stat-box">
                <div class="stat-value" id="fps">0</div>
                <div class="stat-label">FPS</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="frame-count">0</div>
                <div class="stat-label">Frames</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="resolution">-</div>
                <div class="stat-label">Resolución</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="status">⏹️</div>
                <div class="stat-label">Estado</div>
            </div>
        </div>

        <div class="controls">
            <div class="form-group">
                <label>URL de YouTube:</label>
                <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=..." value="">
            </div>
            
            <div class="row" style="grid-template-columns: 1fr 1fr 0.6fr;">
                <div class="form-group">
                    <label>Resolución:</label>
                    <select id="resolution-select">
                        <option value="480">480p</option>
                        <option value="720" selected>720p</option>
                        <option value="1080">1080p</option>
                        <option value="0">Original</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Calidad: <span id="quality-value" style="color:#ff006e; font-weight:bold;">85%</span></label>
                    <input type="range" id="quality" min="10" max="95" value="85" style="margin-top:5px;">
                </div>
                <div class="form-group">
                    <label>FPS:</label>
                    <select id="fps-limit">
                        <option value="0" >Max</option>
                        <option value="60">60</option>
                        <option value="30" selected>30</option>
                        <option value="24">24</option>
                        <option value="15">15</option>
                    </select>
                </div>
            </div>
            
            <div class="form-group">
                <label>🎵 Sync Audio: <span id="audio-sync-value" style="color:#ff006e; font-weight:bold;">0.0s</span></label>
                <input type="range" id="audio-sync" min="-2" max="2" step="0.05" value="0" style="margin-top:5px;">
                <small style="color:#888;">◄ retrasa audio &nbsp;|&nbsp; adelanta audio ►</small>
            </div>

            <div class="row-buttons">
                <div class="buttons-row">
                    <button id="start-btn" onclick="startStream()">▶️ Iniciar</button>
                    <button id="stop-btn" onclick="playlistMode=false; stopStream()" style="display:none; background: #ff4444;">⏹️ Detener</button>
                    <button id="pause-btn" onclick="togglePause()" style="display:none; background: linear-gradient(45deg, #ffd60a, #ffc300);">⏸️ Pausar</button>
                    <button id="fullscreen-btn" onclick="toggleFullScreen()" style="background: linear-gradient(45deg, #00b4d8, #0077b6);">⛶ Ampliar</button>
                    <button id="toggle-search-btn" onclick="toggleSearchPanel()" style="background: linear-gradient(45deg, #00b4d8, #0077b6);">🔍 Ocultar</button>
                </div>
            </div>
            
            <div id="error-msg" class="error"></div>
             <!-- Area de logs -->
            <div id="console-logs" style="margin-top: 20px; background: #000; color: #0f0; padding: 10px; font-family: monospace; height: 150px; overflow-y: scroll; display: none;">
                <div>--- Logs del Sistema ---</div>
            </div>
            <button onclick="document.getElementById('console-logs').style.display='block'" style="margin-top: 10px; background: #333; font-size: 12px; padding: 5px; width: auto;">Mostrar Log</button>
        </div>

        <!-- Search Panel -->
        <div class="search-panel" id="search-panel">
            <h3 style="color: #ff006e; margin-bottom: 15px; font-size: 18px;">🔍 Buscar en YouTube</h3>
            <div class="search-input-group">
                <input type="text" id="search-input" placeholder="Escribe para buscar videos..." onkeypress="if(event.key === 'Enter') searchVideos()">
                <button class="search-btn" onclick="searchVideos()">Buscar</button>
            </div>
            <div class="search-loading" id="search-loading">
                <div class="spinner"></div>
                <p>Buscando videos...</p>
            </div>
            <div class="search-error" id="search-error"></div>
            <div class="no-results" id="no-results">No se encontraron resultados</div>
            <div class="search-results" id="search-results"></div>
        </div>

        <div id="stream-container">
            <div id="placeholder">Introduce una URL y presiona Iniciar</div>
            <img id="frame-display" alt="Video Frame">
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p style="margin-top: 10px; color: #ff006e;">Conectando...</p>
            </div>
        </div>
        
        <audio id="audio-player" style="display:none;"></audio>

        <div id="floating-controls" style="position: fixed; top: 20px; right: 20px; background: rgba(0,0,0,0.9); padding: 20px; border-radius: 10px; z-index: 1000; display: none; border: 1px solid #ff006e;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="color: #ff006e; margin: 0;">Controles</h3>
                <button onclick="toggleControls()" style="width: auto; padding: 5px 10px; background: #ff006e; font-size: 12px;">✕</button>
            </div>
            <div class="form-group">
                <label>URL de YouTube:</label>
                <input type="text" id="url-floating" placeholder="https://www.youtube.com/watch?v=..." value="" style="font-size: 12px; padding: 8px;">
            </div>
            <button id="start-btn-floating" onclick="startStream()" style="margin-top: 10px;">▶️ Iniciar</button>
            <button id="stop-btn-floating" onclick="playlistMode=false; stopStream()" style="margin-top: 10px; background: #ff4444; display: none;">⏹️ Detener</button>
            <button id="pause-btn-floating" onclick="togglePause()" style="margin-top: 10px; background: linear-gradient(45deg, #ffd60a, #ffc300); display: none;">⏸️ Pausar</button>
        </div>
        


        <!-- Favorites Panel -->
        <div id="favorites-panel" class="favorites-panel">
            <div class="panel-header">
                <h3>⭐ Favoritos</h3>
                <button class="toggle-btn" onclick="toggleFavoritesPanel()">−</button>
            </div>
            <div class="panel-content">
                <div class="add-favorite" style="flex-direction: column; align-items: stretch; gap: 5px;">
                    <input type="text" id="new-favorite-url" placeholder="Pegar URL aquí..." />
                    <div style="display: flex; gap: 5px;">
                         <input type="text" id="new-favorite-name" placeholder="Nombre (opcional)" />
                         <button onclick="addCurrentAsFavorite()" style="background: linear-gradient(45deg, #00b4d8, #0077b6); white-space: nowrap; width: auto; padding: 0 15px;">+ Agregar</button>
                    </div>
                </div>
                <div id="favorites-list" class="favorites-list">
                    <div class="no-favorites">No hay favoritos guardados</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let frameCount = 0;
        let lastTime = Date.now();
        let fpsInterval = null;
        let targetFps = 0;
        let frameInterval = null;
        let frameBuffer = [];
        let isPlaying = false;
        let isPaused = false;
        let pendingAudioUrl = null;
        let audioActivating = false;
        let audioReadyTime = null;  // cuando llega la URL de audio (para sincronizar con el video)
        let videoNativeFps = 25;      // FPS nativo detectado
        let syncInterval = null;      // loop de sincronización A/V
        let latestVideoPts = null;     // PTS real del último frame recibido (segundos)
        let firstFrameTime = null;     // timestamp del primer frame recibido
        let audioPrepared = false;     // audio cargado y listo para reproducir
        let audioSyncOffset = 0;      // offset del slider (segundos a adelantar el audio)

        // ============ FAVORITOS ============
        const FAVORITES_STORAGE_KEY = 'tubetesla_favorites';
        let playlistMode = false;
        let currentPlaylistIndex = -1;

        function loadFavorites() {
            const stored = localStorage.getItem(FAVORITES_STORAGE_KEY);
            return stored ? JSON.parse(stored) : [];
        }

        function saveFavorites(favorites) {
            localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(favorites));
        }

        function renderFavorites() {
            try {
                const favorites = loadFavorites();
                const listContainer = document.getElementById('favorites-list');
                let playAllBtn = document.getElementById('play-all-btn');

                if (favorites.length === 0) {
                    listContainer.innerHTML = '<div class="no-favorites">No hay favoritos guardados</div>';
                    if (playAllBtn) playAllBtn.remove();
                    return;
                }

                // Agregar botón Reproducir Todo si no existe y hay favoritos
                if (!playAllBtn && favorites.length > 0) {
                     playAllBtn = document.createElement('button');
                     playAllBtn.id = 'play-all-btn';
                     playAllBtn.textContent = '▶️ Reproducir Todo';
                     playAllBtn.style.cssText = 'width: 100%; margin-bottom: 10px; padding: 10px; border: none; border-radius: 8px; color: white; font-weight: bold; cursor: pointer; background: linear-gradient(45deg, #2ecc71, #27ae60);';
                     playAllBtn.onclick = playAllFavorites;
                     // Insertar antes de la lista
                     if (listContainer.parentNode) {
                        listContainer.parentNode.insertBefore(playAllBtn, listContainer);
                     }
                } else if (playAllBtn && favorites.length > 0) {
                    // Asegurar que sea visible si estaba oculto/removido (aunque aquí lo creamos o ya está)
                    playAllBtn.style.display = 'block';
                }

                listContainer.innerHTML = favorites.map((fav, index) => `
                    <div class="favorite-item">
                        <div class="favorite-item-title">${escapeHtml(fav.name || 'Sin nombre')}</div>
                        <div class="favorite-item-url" title="${fav.url}">${escapeHtml(fav.url.substring(0, 40))}...</div>
                        <div class="favorite-item-buttons">
                            <button class="load-btn" onclick='loadFavorite(${JSON.stringify(fav.url)})'>▶️ Cargar</button>
                            <button class="delete-btn" onclick="deleteFavorite(${index})">🗑️ Eliminar</button>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Error al renderizar favoritos:', e);
            }
        }

        function playAllFavorites() {
            const favorites = loadFavorites();
            if (favorites.length === 0) return;
            
            playlistMode = true;
            currentPlaylistIndex = 0;
            const fav = favorites[0];
            loadFavorite(fav.url);
            showError(`Reproduciendo lista: ${favorites.length} videos`, false);
        }

        function playNextFavorite() {
            if (!playlistMode) return;
            
            const favorites = loadFavorites();
            currentPlaylistIndex++;
            
            if (currentPlaylistIndex < favorites.length) {
                const fav = favorites[currentPlaylistIndex];
                loadFavorite(fav.url);
                showError(`Reproduciendo ${currentPlaylistIndex + 1}/${favorites.length}: ${fav.name || 'Sin nombre'}`, false);
            } else {
                playlistMode = false;
                currentPlaylistIndex = -1;
                showError('Lista de reproducción finalizada', false);
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        function addCurrentAsFavorite() {
            try {
                // Leer inputs del panel de favoritos
                const urlInput = document.getElementById('new-favorite-url');
                const nameInput = document.getElementById('new-favorite-name');
                
                const url = (urlInput.value || '').trim();
                const name = (nameInput.value || '').trim();
                
                if (!url) {
                    showError('Por favor pega una URL en el campo de favoritos', true);
                    return;
                }

                let favorites = [];
                try {
                     favorites = loadFavorites();
                     if (!Array.isArray(favorites)) favorites = [];
                } catch(e) {
                    favorites = [];
                }

                // Verificar si ya existe EXACTAMENTE
                // Usamos un loop simple para evitar problemas con .find en objetos raros
                let existingIndex = -1;
                for (let i = 0; i < favorites.length; i++) {
                    if (favorites[i].url === url) {
                        existingIndex = i;
                        break;
                    }
                }
                
                if (existingIndex !== -1) {
                    const existingName = favorites[existingIndex].name || 'Sin nombre';
                    const confirmMsg = `URL duplicada detectada:\n\nURL: ${url}\n\nYa existe como: "${existingName}"\n\n¿Quieres guardarla de todas formas como nuevo favorito?`;
                    
                    if (!confirm(confirmMsg)) {
                        return; // Cancelado por el usuario
                    }
                }

                // Agregar nuevo favorito
                favorites.push({ url: url, name: name || null });
                saveFavorites(favorites);
                
                // Limpiar campos
                urlInput.value = '';
                nameInput.value = '';
                
                renderFavorites();
                showError(`✅ Añadido. Total favoritos: ${favorites.length}`, false);
                
            } catch (e) {
                console.error('Error FATAL al agregar favorito:', e);
                showError('Error interno: ' + e.message, true);
            }
        }

        function loadFavorite(url) {
            try {
                document.getElementById('url').value = url;
                document.getElementById('url-floating').value = url;
                startStream();
            } catch (e) {
                console.error('Error al cargar favorito:', e);
                showError('Error: ' + e.message, true);
            }
        }

        function deleteFavorite(index) {
            try {
                if (confirm('¿Estás seguro de que deseas eliminar este favorito?')) {
                    const favorites = loadFavorites();
                    favorites.splice(index, 1);
                    saveFavorites(favorites);
                    renderFavorites();
                    showError('✅ Favorito eliminado', false);
                }
            } catch (e) {
                console.error('Error al eliminar favorito:', e);
                showError('Error: ' + e.message, true);
            }
        }

        function toggleFavoritesPanel() {
            const panel = document.getElementById('favorites-panel');
            panel.classList.toggle('collapsed');
            const btn = panel.querySelector('.toggle-btn');
            if (panel.classList.contains('collapsed')) {
                btn.textContent = '+';
            } else {
                btn.textContent = '−';
            }
        }

        function toggleSearchPanel() {
            const panel = document.getElementById('search-panel');
            const btn = document.getElementById('toggle-search-btn');
            panel.classList.toggle('hidden');
            
            if (panel.classList.contains('hidden')) {
                btn.textContent = '🔍 Mostrar';
            } else {
                btn.textContent = '🔍 Ocultar';
            }
        }

        // ============ FIN FAVORITOS ============

        document.getElementById('quality').addEventListener('input', (e) => {
            document.getElementById('quality-value').textContent = e.target.value + '%';
        });
        
        let syncAdjustTimer = null;
        document.getElementById('audio-sync').addEventListener('input', (e) => {
            audioSyncOffset = parseFloat(e.target.value);
            const sign = audioSyncOffset >= 0 ? '+' : '';
            document.getElementById('audio-sync-value').textContent = sign + audioSyncOffset.toFixed(2) + 's';

            // Cambiar el seek del audio para sincronizar
            // Solo funciona para ADELANTAR el audio (seek hacia adelante)
            // Los streams HTTP en vivo no permiten retrasar (seek hacia atrás)
            const ap = document.getElementById('audio-player');
            if (ap && audioSyncOffset > 0) {
                const newTime = ap.currentTime + audioSyncOffset;
                if (newTime > 0 && newTime < ap.duration) {
                    ap.currentTime = newTime;
                    log(`[Sync] Seek audio a ${newTime.toFixed(2)}s (+${audioSyncOffset.toFixed(2)}s)`);
                }
            }
        });
        
        // Sincronizar controles flotantes con principales
        document.getElementById('url').addEventListener('input', (e) => {
            document.getElementById('url-floating').value = e.target.value;
        });
        document.getElementById('url-floating').addEventListener('input', (e) => {
            document.getElementById('url').value = e.target.value;
        });

        // Cargar favoritos al iniciar
        renderFavorites();



        function toggleControls() {
            const container = document.querySelector('.container');
            const floatingControls = document.getElementById('floating-controls');
            const statsDiv = document.querySelector('.stats');
            const videoControlsBar = document.getElementById('video-controls-bar');
            
            if (floatingControls.style.display === 'block') {
                // Mostrar todos los controles
                floatingControls.style.display = 'none';
                container.style.display = 'block';
                document.body.style.background = 'linear-gradient(rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0.7)), url(/static/tesla-roadster.jpg)';
                document.body.style.backgroundSize = 'cover';
                document.body.style.backgroundPosition = 'center';
                document.body.style.backgroundAttachment = 'fixed';
            } else {
                // Modo solo video - ocultar controles principales
                container.style.display = 'none';
                floatingControls.style.display = 'block';
                document.body.style.background = 'linear-gradient(rgba(0, 0, 0, 0.9), rgba(0, 0, 0, 0.9)), url(/static/tesla-roadster.jpg)';
                document.body.style.backgroundSize = 'cover';
                document.body.style.backgroundPosition = 'center';
                document.body.style.backgroundAttachment = 'fixed';
            }
        }

        function log(msg) {
            console.log(msg);
            const div = document.createElement('div');
            div.textContent = `> ${msg}`;
            document.getElementById('console-logs').appendChild(div);
            document.getElementById('console-logs').scrollTop = document.getElementById('console-logs').scrollHeight;
        }

        function updateVideoSize() {
            const size = document.getElementById('video-size').value;
            const container = document.getElementById('stream-container');
            const frameDisplay = document.getElementById('frame-display');
            
            // Restaurar estilos base del contenedor
            container.style.width = '';
            container.style.maxWidth = '';
            container.style.marginLeft = '';
            container.style.left = '';
            container.style.margin = '0 auto';
            
            // Restaurar estilos base del video
            frameDisplay.style.width = '';
            frameDisplay.style.maxWidth = '';
            frameDisplay.style.height = '';

            switch(size) {
                case 'small':
                    container.style.maxWidth = '640px';
                    frameDisplay.style.width = '50%';
                    break;
                case 'medium':
                    container.style.maxWidth = '854px';
                    frameDisplay.style.width = '75%';
                    break;
                case 'large':
                    container.style.maxWidth = '100%';
                    frameDisplay.style.width = '100%';
                    break;
                case 'theater':
                    container.style.width = '98vw';
                    container.style.maxWidth = 'none';
                    container.style.position = 'relative';
                    container.style.left = '50%';
                    container.style.marginLeft = '-49vw';
                    frameDisplay.style.width = '100%';
                    frameDisplay.style.maxHeight = '95vh';
                    break;
            }
        }

        function updateFPS() {
            const now = Date.now();
            const diff = now - lastTime;
            if (diff >= 1000) {
                const fps = Math.round((frameCount * 1000) / diff);
                document.getElementById('fps').textContent = fps;
                frameCount = 0;
                lastTime = now;
            }
        }

        // ============ BUSCADOR DE YOUTUBE ============
        async function searchVideos() {
            const searchInput = document.getElementById('search-input');
            const query = searchInput.value.trim();
            
            if (!query) {
                showSearchError('Por favor introduce un término de búsqueda');
                return;
            }

            const searchLoading = document.getElementById('search-loading');
            const searchResults = document.getElementById('search-results');
            const searchError = document.getElementById('search-error');
            const noResults = document.getElementById('no-results');

            // Reset UI
            searchLoading.classList.add('active');
            searchResults.classList.remove('active');
            searchError.classList.remove('active');
            noResults.classList.remove('active');
            searchResults.innerHTML = '';

            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&max_results=10`);
                const data = await response.json();

                searchLoading.classList.remove('active');

                if (data.error) {
                    showSearchError(data.error);
                    return;
                }

                if (!data.results || data.results.length === 0) {
                    noResults.classList.add('active');
                    return;
                }

                // Renderizar resultados
                searchResults.innerHTML = data.results.map(video => `
                    <div class="search-result-item">
                        <img class="search-result-thumb" src="${video.thumbnail}" alt="${escapeHtml(video.title)}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22160%22 height=%2290%22><rect fill=%22%23333%22 width=%22160%22 height=%2290%22/><text fill=%22%23666%22 x=%2250%%22 y=%2250%%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22>Sin imagen</text></svg>'">
                        <div class="search-result-info">
                            <div class="search-result-title" title="${escapeHtml(video.title)}">${escapeHtml(video.title)}</div>
                            <div class="search-result-meta">
                                📺 ${escapeHtml(video.uploader)} 
                                ${video.duration ? `| ⏱️ ${video.duration}` : ''}
                                ${video.view_count ? `| 👁️ ${formatViews(video.view_count)}` : ''}
                            </div>
                            <div class="search-result-buttons">
                                <button class="search-result-play-btn" onclick='playFromSearch("${video.url}", "${escapeHtml(video.title).replace(/'/g, "\\'")}")'>▶️ Reproducir</button>
                                <button class="search-result-fav-btn" onclick='addToFavoritesFromSearch("${video.url}", "${escapeHtml(video.title).replace(/'/g, "\\'")}")'>⭐ Favorito</button>
                            </div>
                        </div>
                    </div>
                `).join('');

                searchResults.classList.add('active');

            } catch (error) {
                searchLoading.classList.remove('active');
                showSearchError('Error al buscar: ' + error.message);
            }
        }

        function playFromSearch(url, title) {
            document.getElementById('url').value = url;
            document.getElementById('url-floating').value = url;
            showError(`Reproduciendo: ${title}`, false);
            startStream();
            
            // Ocultar resultados
            document.getElementById('search-results').classList.remove('active');
        }

        function addToFavoritesFromSearch(url, title) {
            let favorites = [];
            try {
                favorites = loadFavorites();
                if (!Array.isArray(favorites)) favorites = [];
            } catch(e) {
                favorites = [];
            }

            // Verificar si ya existe
            let existingIndex = -1;
            for (let i = 0; i < favorites.length; i++) {
                if (favorites[i].url === url) {
                    existingIndex = i;
                    break;
                }
            }
            
            if (existingIndex !== -1) {
                showSearchError('⚠️ Este video ya está en tus favoritos');
                return;
            }

            // Agregar nuevo favorito
            favorites.push({ url: url, name: title });
            saveFavorites(favorites);
            renderFavorites();
            
            showSearchError(`✅ "${title}" añadido a favoritos`, false);
        }

        function showSearchError(message, isError = true) {
            const searchError = document.getElementById('search-error');
            searchError.textContent = message;
            searchError.classList.remove('success');
            
            if (!isError) {
                searchError.classList.add('success');
            }
            
            searchError.classList.add('active');
            
            setTimeout(() => {
                searchError.classList.remove('active', 'success');
            }, 5000);
        }

        function formatViews(views) {
            if (views >= 1000000) {
                return (views / 1000000).toFixed(1) + 'M';
            } else if (views >= 1000) {
                return (views / 1000).toFixed(1) + 'K';
            }
            return views.toString();
        }
        // ============ FIN BUSCADOR ============

        function startStream() {
            const url = document.getElementById('url').value;
            if (!url) {
                showError('Por favor introduce una URL válida');
                return;
            }

            stopStream();

            document.getElementById('start-btn').style.display = 'none';
            document.getElementById('stop-btn').style.display = 'block';
            document.getElementById('pause-btn').style.display = 'block';
            document.getElementById('start-btn-floating').style.display = 'none';
            document.getElementById('stop-btn-floating').style.display = 'block';
            document.getElementById('pause-btn-floating').style.display = 'block';
            document.getElementById('placeholder').style.display = 'none';
            document.getElementById('frame-display').style.display = 'block';
            document.getElementById('loading').style.display = 'block';
            document.getElementById('error-msg').style.display = 'none';
            document.getElementById('status').textContent = '🟡';

            log(`Iniciando conexión a: ${url}`);

            // Desbloquear audio DENTRO del gesto de usuario (click)
            const ap = document.getElementById('audio-player');
            ap.muted = false;
            ap.volume = 1.0;
            // Reproducir y pausar inmediatamente para desbloquear
            ap.play().then(() => {
                ap.pause();
                log('[Audio] Desbloqueado OK');
            }).catch(e => {
                log('[Audio] No se pudo desbloquear: ' + e.message);
            });

            frameCount = 0;
            lastTime = Date.now();
            fpsInterval = setInterval(updateFPS, 500);

            const configPayload = {
                url: url,
                resolution: document.getElementById('resolution-select').value,
                quality: parseInt(document.getElementById('quality').value),
                fps_limit: parseInt(document.getElementById('fps-limit').value || 0),
                frame_skip: 1
            };

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/stream`);

            ws.onopen = () => {
                document.getElementById('status').textContent = '🟡';
                setTimeout(() => { ws.send(JSON.stringify(configPayload)); }, 300);
            };

            ws.onmessage = (event) => {
                if (event.data instanceof Blob) {
                    const objUrl = URL.createObjectURL(event.data);
                    const img = document.getElementById('frame-display');
                    img.onload = () => URL.revokeObjectURL(objUrl);
                    if (document.getElementById('loading').style.display !== 'none') {
                        document.getElementById('loading').style.display = 'none';
                        document.getElementById('status').textContent = '🟢';
                        firstFrameTime = Date.now();
                        
                        // Primer frame recibido: audio ya debería estar sonando
                        const ap = document.getElementById('audio-player');
                        if (audioPrepared && ap && !ap.paused) {
                            const pipelineDelay = (firstFrameTime - audioReadyTime) / 1000;
                            log(`[Audio] Pipeline delay: ${pipelineDelay.toFixed(2)}s, audio ya sonando`);
                        } else if (audioPrepared && ap && ap.paused) {
                            // Fallback: intentar reproducir si no se pudo antes
                            log('[Audio] Intentando reproducir en primer frame...');
                            ap.play().catch(e => log('[Audio] Error: ' + e.message));
                        }
                        
                        // Sync loop simplificado: solo monitor, no interfiere con el slider
                        if (syncInterval === null) {
                            syncInterval = setInterval(() => {
                                const ap = document.getElementById('audio-player');
                                if (!ap || ap.paused) return;
                                log(`[A/V] audio.currentTime=${ap.currentTime.toFixed(1)}s`);
                            }, 5000);
                        }
                    }
                    if (!isPaused) {
                        img.src = objUrl;
                        frameCount++;
                        document.getElementById('frame-count').textContent =
                            parseInt(document.getElementById('frame-count').textContent) + 1;
                    }
                } else {
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.type === 'pts') {
                            latestVideoPts = msg.t;
                        } else if (msg.type === 'info') {
                            document.getElementById('resolution').textContent = msg.resolution;
                            if (msg.native_fps) {
                                videoNativeFps = msg.native_fps;
                                log(`FPS nativo detectado: ${msg.native_fps}`);
                            }
                            if (msg.audio_session_id) {
                                // Usar el proxy local con session_id (la URL de audio se queda en el servidor)
                                const audioSrc = '/proxy-audio?session_id=' + msg.audio_session_id;
                                log('[Audio] Proxy session: ' + msg.audio_session_id);
                                
                                audioReadyTime = Date.now();
                                const ap = document.getElementById('audio-player');
                                
                                if (!ap) {
                                    log('[Audio] ✗ ERROR: audio-player no encontrado');
                                    return;
                                }
                                
                                // Event listeners para depuración
                                ap.onerror = (e) => log('[Audio] ✗ Error event: code=' + (ap.error ? ap.error.code : 'null') + ' msg=' + (ap.error ? ap.error.message : 'unknown'));
                                ap.onloadeddata = () => log('[Audio] ✓ loadeddata event');
                                ap.oncanplay = () => log('[Audio] ✓ canplay event');
                                ap.onplaying = () => log('[Audio] ✓ playing event');
                                ap.onwaiting = () => log('[Audio] ⏳ waiting event');
                                ap.onstalled = () => log('[Audio] ⚠ stalled event');
                                ap.onprogress = () => log('[Audio] 📥 progress event');
                                ap.onloadstart = () => log('[Audio] 🔄 loadstart event');
                                
                                log('[Audio] Asignando src...');
                                ap.src = audioSrc;
                                ap.volume = 1.0;
                                ap.muted = false;
                                audioPrepared = true;
                                log('[Audio] URL asignada, llamando a play()...');
                                
                                // Intentar reproducir con timeout
                                const playPromise = ap.play();
                                const playTimeout = setTimeout(() => {
                                    log('[Audio] ⏱️ play() timeout - promesa pendiente');
                                }, 3000);
                                
                                playPromise.then(() => {
                                    clearTimeout(playTimeout);
                                    log('[Audio] ✓ Reproduciendo OK');
                                }).catch(e => {
                                    clearTimeout(playTimeout);
                                    log('[Audio] ✗ Error play(): ' + e.message);
                                    // Segundo intento con interacción del usuario
                                    document.body.addEventListener('click', function audioUnlock() {
                                        ap.play().then(() => log('[Audio] ✓ Reproduciendo tras click')).catch(e2 => log('[Audio] ✗ Error: ' + e2.message));
                                        document.body.removeEventListener('click', audioUnlock);
                                    }, { once: true });
                                });
                            }
                        } else if (msg.type === 'status') {
                            const p = document.querySelector('.loading p');
                            if (p) p.textContent = msg.message;
                        } else if (msg.type === 'error') {
                            showError(msg.message);
                            stopStream();
                        } else if (msg.type === 'complete') {
                            document.getElementById('status').textContent = '✅';
                            stopStream(false);
                            if (playlistMode) setTimeout(playNextFavorite, 1000);
                        }
                    } catch(e) {}
                }
            };

            ws.onerror = () => { showError('Error de conexión WebSocket'); stopStream(); };
            ws.onclose = (e) => { if (isPlaying) stopStream(false); };

            isPlaying = true;
        }

        function stopStream(reset = true) {
            isPlaying = false;

            if (ws) { ws.close(); ws = null; }
            if (fpsInterval) { clearInterval(fpsInterval); fpsInterval = null; }

            // Solo matar el audio en parada manual (reset=true)
            // Cuando el video termina naturalmente, dejar que el audio siga sonando
            if (reset) {
                const audioPlayer = document.getElementById('audio-player');
                audioPlayer.pause();
                audioPlayer.src = '';
                pendingAudioUrl = null;
                audioReadyTime = null;
                audioActivating = false;
                audioPrepared = false;
                firstFrameTime = null;
                if (syncInterval) { clearInterval(syncInterval); syncInterval = null; }
                latestVideoPts = null;
            }

            document.getElementById('start-btn').style.display = 'block';
            document.getElementById('stop-btn').style.display = 'none';
            document.getElementById('pause-btn').style.display = 'none';
            document.getElementById('loading').style.display = 'none';
            document.getElementById('frame-display').style.display = 'none';
            document.getElementById('frame-display').src = '';
            document.getElementById('placeholder').style.display = 'block';

            if (reset) {
                document.getElementById('status').textContent = '⏹️';
                document.getElementById('fps').textContent = '0';
                isPaused = false;
                const pauseBtn = document.getElementById('pause-btn');
                const pauseBtnFloat = document.getElementById('pause-btn-floating');
                pauseBtn.textContent = '⏸️ Pausar';
                pauseBtn.style.background = 'linear-gradient(45deg, #ffd60a, #ffc300)';
                pauseBtnFloat.textContent = '⏸️ Pausar';
                pauseBtnFloat.style.background = 'linear-gradient(45deg, #ffd60a, #ffc300)';
            }

            document.getElementById('start-btn-floating').style.display = 'block';
            document.getElementById('stop-btn-floating').style.display = 'none';
            document.getElementById('pause-btn-floating').style.display = 'none';
        }

        function togglePause() {
            if (!ws) return;

            isPaused = !isPaused;
            const audioPlayer = document.getElementById('audio-player');
            const pauseBtn = document.getElementById('pause-btn');
            const pauseBtnFloating = document.getElementById('pause-btn-floating');
            const status = document.getElementById('status');

            if (isPaused) {
                audioPlayer.pause();
                pauseBtn.textContent = '▶️ Reanudar';
                pauseBtnFloating.textContent = '▶️ Reanudar';
                pauseBtn.style.background = 'linear-gradient(45deg, #00b4d8, #0077b6)';
                pauseBtnFloating.style.background = 'linear-gradient(45deg, #00b4d8, #0077b6)';
                status.textContent = '⏸️';
                log("Stream pausado");
            } else {
                audioPlayer.play();
                pauseBtn.textContent = '⏸️ Pausar';
                pauseBtnFloating.textContent = '⏸️ Pausar';
                pauseBtn.style.background = 'linear-gradient(45deg, #ffd60a, #ffc300)';
                pauseBtnFloating.style.background = 'linear-gradient(45deg, #ffd60a, #ffc300)';
                status.textContent = '🟢';
                log("Stream reanudado");
            }
        }

        function toggleFullScreen() {
            const elem = document.getElementById('stream-container');
            const btn = document.getElementById('fullscreen-btn');
            if (!document.fullscreenElement) {
                elem.requestFullscreen().then(() => {
                    btn.textContent = '⛶ Salir';
                }).catch(err => {
                    console.error('Fullscreen error:', err.message);
                });
            } else {
                document.exitFullscreen();
            }
        }

        document.addEventListener('fullscreenchange', () => {
            const btn = document.getElementById('fullscreen-btn');
            if (btn) btn.textContent = document.fullscreenElement ? '⛶ Salir' : '⛶ Ampliar';
        });

        function showError(msg, isError = true) {
            const errDiv = document.getElementById('error-msg');
            errDiv.textContent = isError ? ('⚠️ ' + msg) : msg;
            errDiv.style.display = 'block';
            setTimeout(() => errDiv.style.display = 'none', 5000);
        }

        window.onbeforeunload = () => { stopStream(); };
    </script>
</body>
</html>
"""

class VideoStreamProcessor:
    def __init__(self):
        self.active = True
        self.frame_queue = queue.Queue(maxsize=5)
        self.error = None
        self.skip_frames = 0  # frames a descartar para sincronizar con el audio
        self.current_pts = 0.0  # timestamp del frame de video más reciente (segundos)
        self._cap = None   # referencia a cv2.VideoCapture para liberarlo en stop()
        self._proc = None  # referencia a subprocess ffmpeg para matarlo en stop()

    def stop(self):
        """Detiene el procesamiento de forma inmediata liberando recursos de red/CPU."""
        self.active = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
    
    def get_stream_info(self, youtube_url, max_resolution):
        """Extrae URLs de video y audio usando yt-dlp. Se prioriza H.264/MP4 para compatibilidad con OpenCV."""
        ydl_opts = {
            # Priorizar H.264 (avc) ya que AV1/VP9 no son decodificables por OpenCV en esta plataforma
            'format': (
                f'bestvideo[height<={max_resolution}][vcodec^=avc]+bestaudio/'
                f'bestvideo[height<={max_resolution}][vcodec^=avc]/'
                f'best[height<={max_resolution}][vcodec^=avc]/'
                f'best[height<={max_resolution}]/'
                f'best'
            ),
            'quiet': True,
            'no_warnings': True,
            # Habilitar descarga de componentes remotos para resolver JS challenges de YouTube
            'remote_components': ['ejs:github'],
        }
        
        video_url = None
        audio_url = None
        audio_http_headers = {}  # headers HTTP necesarios para descargar el audio
        audio_mime = 'audio/webm'  # MIME type del audio
        width = 0
        height = 0
        native_fps = 0
        
        try:
            print(f"Starting yt-dlp extraction for: {youtube_url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                print("yt-dlp extraction complete")
                
                # Obtener headers HTTP por defecto de yt-dlp
                default_headers = ydl.params.get('http_headers', {})
                
                if 'requested_formats' in info:
                    for f in info['requested_formats']:
                        if f.get('vcodec') != 'none':
                            video_url = f['url']
                            width = f.get('width', 0)
                            height = f.get('height', 0)
                            native_fps = f.get('fps') or 0
                            print(f"Video URL found: {video_url[:30]}... fps={native_fps}")
                        if f.get('acodec') != 'none':
                            audio_url = f['url']
                            # Extraer headers HTTP específicos del formato de audio
                            audio_http_headers = f.get('http_headers', default_headers) or default_headers
                            audio_mime = f.get('ext', 'webm')
                            if audio_mime == 'webm':
                                audio_mime = 'audio/webm'
                            elif audio_mime == 'm4a':
                                audio_mime = 'audio/mp4'
                            else:
                                audio_mime = f'audio/{audio_mime}'
                            print(f"Audio URL found: {audio_url[:30]}... mime={audio_mime}")
                            print(f"Audio HTTP headers keys: {list(audio_http_headers.keys())}")
                else:
                    video_url = info['url']
                    audio_url = info['url']
                    audio_http_headers = info.get('http_headers', default_headers) or default_headers
                    width = info.get('width', 0)
                    height = info.get('height', 0)
                    native_fps = info.get('fps') or 0
                    print(f"Combined URL found, fps={native_fps}")
                    
        except Exception as e:
            print(f"Error extracting stream info: {e}")
            raise e
            
        return video_url, audio_url, audio_http_headers, audio_mime, width, height, native_fps
    
    def _put_frame_jpeg(self, jpeg_bytes):
        """Encola un frame JPEG, descartando si la cola está llena."""
        try:
            self.frame_queue.put(jpeg_bytes, block=False)
        except queue.Full:
            pass

    def process_frames(self, video_url, settings):
        """Procesa frames en thread separado, con fallback a ffmpeg."""
        import subprocess, time

        # Intentar cv2 pero verificar que realmente puede leer al menos un frame
        cap = cv2.VideoCapture(video_url)
        if cap.isOpened():
            ret, first_frame = cap.read()
            if ret and first_frame is not None:
                print("cv2.VideoCapture abierto correctamente")
                self._process_frames_cv2(cap, settings, first_frame=first_frame)
            else:
                cap.release()
                print("cv2 abrio la URL pero fallo al leer frames, usando ffmpeg...")
                self._process_frames_ffmpeg(video_url, settings)
        else:
            cap.release()
            print("cv2 no pudo abrir la URL, usando ffmpeg como decodificador de frames...")
            self._process_frames_ffmpeg(video_url, settings)

    def _process_frames_cv2(self, cap, settings, first_frame=None):
        """Decodifica frames usando cv2 (para URLs directas de MP4)."""
        import time
        try:
            self._cap = cap  # guardar referencia para stop() inmediato
            frame_count = 0
            skip = settings.get('frame_skip', 1)

            # Si se leyó un frame de prueba antes, procesarlo primero
            pending_frame = first_frame

            while self.active:
                if pending_frame is not None:
                    ret, frame = True, pending_frame
                    pending_frame = None
                else:
                    ret, frame = cap.read()
                if not ret:
                    print("cv2: fin de stream o error de lectura")
                    break

                # Descartar frames para sincronizar con el audio
                to_skip = self.skip_frames
                if to_skip > 0:
                    self.skip_frames = 0
                    print(f"[sync] cv2: descartando {to_skip} frames")
                    for _ in range(to_skip - 1):
                        cap.read()
                    continue

                frame_count += 1
                if frame_count % skip != 0:
                    continue

                if settings['max_width'] > 0 and frame.shape[1] > settings['max_width']:
                    ratio = settings['max_width'] / frame.shape[1]
                    new_size = (settings['max_width'], int(frame.shape[0] * ratio))
                    frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

                # Guardar PTS real de este frame
                self.current_pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=settings['quality'], optimize=True)
                self._put_frame_jpeg(buf.getvalue())

                if settings.get('fps_limit', 0) > 0:
                    time.sleep(1.0 / settings['fps_limit'])

            cap.release()
            print("cv2: VideoCapture liberado")
        except Exception as e:
            cap.release()
            print(f"Error en _process_frames_cv2: {e}")
            self.error = str(e)
            self.active = False

    def _process_frames_ffmpeg(self, video_url, settings):
        """Decodifica frames usando ffmpeg (soporta DASH, HLS, manifiestos, etc.)."""
        import subprocess, time

        max_width = settings.get('max_width', 1280)
        native_fps = settings.get('native_fps', 0)
        fps_limit = settings.get('fps_limit', 0)
        # Si el usuario eligió "Max" (fps_limit=0), usar el FPS nativo del video
        fps = fps_limit if fps_limit > 0 else (native_fps if native_fps > 0 else 25)
        fps = min(fps, 60)
        print(f"[ffmpeg] FPS nativo={native_fps}, fps_limit={fps_limit}, usando fps={fps}")
        quality = settings.get('quality', 85)
        # ffmpeg MJPEG quality: 2=best, 31=worst; mapear calidad 0-100 -> 2-20
        ffmpeg_q = max(2, min(20, int(20 - (quality / 100) * 18)))

        # Escalar vídeo preservando aspect ratio
        vf = f"scale='min({max_width},iw)':-2"

        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
            '-allowed_extensions', 'ALL',
            '-i', video_url,
            '-an',            # sin audio (se maneja por separado)
            '-vf', vf,
            '-r', str(fps),   # limitar fps de salida
            '-q:v', str(ffmpeg_q),
            '-f', 'mjpeg',
            'pipe:1'
        ]

        print(f"ffmpeg cmd: {' '.join(cmd[:8])}...")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    bufsize=0)
        except Exception as e:
            print(f"No se pudo lanzar ffmpeg: {e}")
            self.error = f"ffmpeg no disponible: {e}"
            self.active = False
            return

        self._proc = proc  # guardar referencia para stop() inmediato
        buf = b''
        ffmpeg_frame_index = 0
        try:
            while self.active:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    if proc.poll() is not None:
                        stderr_out = proc.stderr.read().decode('utf-8', errors='replace')
                        if stderr_out:
                            print(f"ffmpeg stderr: {stderr_out[:300]}")
                        print("ffmpeg: proceso terminado")
                        break
                    continue

                buf += chunk

                # Extraer frames JPEG completos del stream MJPEG
                while True:
                    start = buf.find(b'\xff\xd8')
                    if start == -1:
                        buf = b''
                        break
                    end = buf.find(b'\xff\xd9', start + 2)
                    if end == -1:
                        buf = buf[start:]
                        break
                    jpeg = buf[start:end + 2]
                    buf = buf[end + 2:]

                    # Siempre actualizar PTS (incluso cuando saltemos el frame)
                    ffmpeg_frame_index += 1
                    self.current_pts = ffmpeg_frame_index / fps

                    # Descartar frames para sincronizar con el audio
                    to_skip = self.skip_frames
                    if to_skip > 0:
                        self.skip_frames = max(0, to_skip - 1)
                        continue

                    self._put_frame_jpeg(jpeg)

        except Exception as e:
            print(f"Error en _process_frames_ffmpeg: {e}")
            self.error = str(e)
            self.active = False
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
            print("ffmpeg: proceso detenido")

@app.get("/api/search")
async def search_videos(q: str, max_results: int = 10):
    """Busca videos en YouTube usando yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'max_downloads': max_results,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Usar ytsearch para buscar
            search_url = f'ytsearch{max_results}:{q}'
            info = ydl.extract_info(search_url, download=False)
            
            results = []
            if 'entries' in info:
                for entry in info['entries']:
                    results.append({
                        'title': entry.get('title', 'Sin título'),
                        'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        'thumbnail': entry.get('thumbnail', ''),
                        'duration': entry.get('duration_string', ''),
                        'view_count': entry.get('view_count', 0),
                        'uploader': entry.get('uploader', 'Desconocido'),
                    })
            
            return {'results': results}
    except Exception as e:
        return {'error': str(e), 'results': []}

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_CONTENT

@app.get("/proxy-audio")
async def proxy_audio(session_id: str):
    """Proxy de audio: usa yt-dlp para descargar y ffmpeg para convertir a MP3.
    yt-dlp maneja toda la autenticación de YouTube internamente."""
    print(f"[proxy-audio] ========== REQUEST RECIBIDO ==========")
    print(f"[proxy-audio] Session ID: {session_id}")
    
    session = audio_sessions.get(session_id)
    if not session:
        print(f"[proxy-audio] ✗ Session no encontrada: {session_id}")
        raise HTTPException(status_code=404, detail="Audio session not found")
    
    youtube_url = session['youtube_url']
    print(f"[proxy-audio] YouTube URL: {youtube_url}")

    async def stream_generator():
        q = session.get('queue')
        if q is None:
            print(f"[proxy-audio] ✗ No hay queue en la session")
            return
        
        bytes_sent = 0
        first_chunk = True
        print(f"[proxy-audio] Drenando queue pre-bufferizada...")
        try:
            while True:
                chunk = await q.get()
                if chunk is None:  # señal de fin
                    break
                if first_chunk:
                    print(f"[proxy-audio] ✓ Primer chunk: {len(chunk)} bytes (pre-bufferizado)")
                    first_chunk = False
                bytes_sent += len(chunk)
                yield chunk
        except Exception as e:
            print(f"[proxy-audio] Error al drear queue: {e}")
        finally:
            print(f"[proxy-audio] Stream terminado. Bytes enviados: {bytes_sent}")

    return StreamingResponse(
        stream_generator(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.get("/api/video-stream")
async def api_video_stream(url: str, resolution: int = 720):
    """Stream sincronizado video+audio usando ffmpeg → fragmented MP4 nativo del navegador"""
    processor = VideoStreamProcessor()
    loop = asyncio.get_running_loop()

    try:
        video_url, audio_url, _audio_headers, _audio_mime, width, height, native_fps = await loop.run_in_executor(
            None,
            processor.get_stream_info,
            url,
            resolution if resolution != 0 else 2160
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not video_url:
        raise HTTPException(status_code=500, detail="No se pudo obtener la URL del video")

    # Comando ffmpeg: muxea video H264 + audio en fragmented MP4 streamable
    if video_url == audio_url:
        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-i', video_url,
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-f', 'mp4', 'pipe:1'
        ]
    else:
        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-i', video_url,
            '-i', audio_url,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-f', 'mp4', 'pipe:1'
        ]

    async def generate():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            print(f"Video stream error: {e}")
        finally:
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass

    return StreamingResponse(
        generate(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        }
    )

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    print(f"🔌 Nueva conexión WebSocket desde: {websocket.client}")
    print(f"   Headers: {websocket.headers}")
    
    try:
        await websocket.accept()
        print(f"✅ Conexión aceptada: {websocket.client}")
        
        processor = None
        print(f"Cliente conectado: {websocket.client}")
    
        # Recibir configuración
        print("Esperando configuración del cliente (JSON)...")
        try:
            # Aumentamos el timeout a 30 segundos para conexiones remotas
            config = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        except asyncio.TimeoutError:
            print("Timeout esperando configuración del cliente")
            await websocket.close()
            return

        print(f"Configuración recibida: {config}")
        
        processor = VideoStreamProcessor()
        
        await websocket.send_json({'type': 'status', 'message': 'Extrayendo información del video...'})

        # Obtener URL del stream
        # Run in executor to avoid blocking main thread (yt-dlp is synchronous)
        loop = asyncio.get_running_loop()
        try:
            print("Invoking get_stream_info...")
            video_url, audio_url, audio_http_headers, audio_mime, width, height, native_fps = await loop.run_in_executor(
                None, 
                processor.get_stream_info,
                config['url'], 
                config['resolution'] if config['resolution'] != '0' else 2160
            )

            if not video_url:
                raise Exception("No se pudo obtener la URL del video")
            
            print(f"Info extracted. Video: {video_url[:20]}... Audio: {audio_url[:20] if audio_url else 'None'}... FPS: {native_fps}")

        except Exception as e:
            print(f"Error in extraction loop: {e}")
            await websocket.send_json({
                'type': 'error',
                'message': f"Error al obtener video: {str(e)}"
            })
            return
        
        await websocket.send_json({'type': 'status', 'message': 'Conectando stream de video...'})

        # Almacenar URL de YouTube original y arrancar el pipeline de audio YA
        audio_session_id = None
        if audio_url:
            import shlex as _shlex
            audio_session_id = str(uuid.uuid4())
            audio_queue = asyncio.Queue(maxsize=100)  # buffer de chunks MP3
            audio_sessions[audio_session_id] = {
                'youtube_url': config['url'],
                'queue': audio_queue,
                'done': False,
                'first_chunk_event': asyncio.Event(),  # se activa cuando llega el primer chunk
            }
            print(f"Audio session creada: {audio_session_id} -> {config['url']}")
            
            # Arrancar pipeline en background AHORA para pre-bufferear
            _safe_url = _shlex.quote(config['url'])
            _shell_cmd = (
                f"yt-dlp -f bestaudio --no-warnings -o - {_safe_url} "
                f"| ffmpeg -loglevel error -i pipe:0 -vn -c:a libmp3lame -b:a 128k -ar 44100 -f mp3 pipe:1"
            )
            
            async def _prefetch_audio(sid, cmd, q):
                proc = None
                try:
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    print(f"[audio-prefetch] Pipeline iniciado PID={proc.pid}")
                    while True:
                        try:
                            chunk = await proc.stdout.read(65536) # mayor chunk para eficiencia
                            if not chunk:
                                break
                            await q.put(chunk)
                            # Señalar que el primer chunk llegó
                            if sid in audio_sessions and not audio_sessions[sid].get('first_chunk_event').is_set():
                                audio_sessions[sid]['first_chunk_event'].set()
                                print(f"[audio-prefetch] ✓ Primer chunk listo ({len(chunk)} bytes)")
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            print(f"[audio-prefetch] Error en lectura: {e}")
                            break
                except Exception as ex:
                    print(f"[audio-prefetch] Error fatal: {ex}")
                finally:
                    if proc:
                        try:
                            # Intentar terminar de forma limpia
                            proc.terminate()
                            await asyncio.wait_for(proc.wait(), timeout=2.0)
                        except Exception:
                            try: proc.kill()
                            except: pass
                    await q.put(None)  # señal de fin
                    if sid in audio_sessions:
                        audio_sessions[sid]['done'] = True
                        audio_sessions[sid]['first_chunk_event'].set()  # desbloquear si hubo error
                    print(f"[audio-prefetch] Pipeline finalizado para {sid}. Queue size: {q.qsize()}")
            
            asyncio.ensure_future(_prefetch_audio(audio_session_id, _shell_cmd, audio_queue))
            
            # Esperar a que el pipeline de audio produzca el primer chunk (máx 10s)
            # Esto asegura que audio y video empiezan a la vez
            first_chunk_event = audio_queue_session = audio_sessions[audio_session_id]['first_chunk_event']
            print("[ws] Esperando primer chunk de audio antes de arrancar el video...")
            try:
                await asyncio.wait_for(first_chunk_event.wait(), timeout=10.0)
                print("[ws] ✓ Audio listo, esperando 1s para que el navegador bufferee...")
                await asyncio.sleep(1.0) # Delay de cortesía
                print("[ws] ✓ Iniciando video sincronizado")
            except asyncio.TimeoutError:
                print("[ws] ⚠ Timeout esperando audio, arrancando video igualmente")

        await websocket.send_json({
            'type': 'info',
            'resolution': f'{width}x{height}',
            'audio_session_id': audio_session_id,
            'native_fps': native_fps
        })
        
        # Configuración de procesamiento
        settings = {
            'max_width': 1280 if config['resolution'] == '0' else int(config['resolution']),
            'quality': config['quality'],
            'fps_limit': config.get('fps_limit', 0),
            'native_fps': native_fps,
            'frame_skip': config.get('frame_skip', 1)
        }
        
        # Iniciar procesamiento en thread
        thread = threading.Thread(
            target=processor.process_frames, 
            args=(video_url, settings)
        )
        thread.start()

        # Enviar frames al cliente. Los mensajes del cliente (skip_frames)
        # se reciben en un task separado usando la misma conexión WebSocket.
        # Usamos una queue asyncio para pasar skip_frames al loop principal de forma segura.
        client_msgs: asyncio.Queue = asyncio.Queue()

        async def recv_client_messages():
            try:
                while processor.active:
                    raw = await websocket.receive()
                    if raw['type'] == 'websocket.disconnect':
                        break
                    if raw.get('text'):
                        import json as _json
                        try:
                            msg = _json.loads(raw['text'])
                            await client_msgs.put(msg)
                        except Exception:
                            pass
            except Exception:
                pass

        recv_task = asyncio.ensure_future(recv_client_messages())

        import time as _time
        last_pts_sent = -1.0
        while processor.active:
            # Procesar mensajes entrantes del cliente (no bloqueante)
            while not client_msgs.empty():
                msg = client_msgs.get_nowait()
                if msg.get('type') == 'skip_frames':
                    n = int(msg.get('count', 0))
                    if n > 0:
                        processor.skip_frames = n
                        print(f"[sync] Saltando {n} frames (pts={processor.current_pts:.1f}s)")

            try:
                # IMPORTANTE: usar run_in_executor para no bloquear el event loop.
                # Un get() bloqueante impediría procesar las peticiones HTTP del proxy de audio.
                frame_data = await loop.run_in_executor(
                    None, 
                    lambda: processor.frame_queue.get(timeout=1.0)
                )
                await websocket.send_bytes(frame_data)
                
                # DAR UN RESPIRO AL EVENT LOOP (Crítico para que el audio pueda entrar)
                await asyncio.sleep(0.01) 

                # Enviar PTS una vez por segundo
                pts = processor.current_pts
                if pts - last_pts_sent >= 1.0:
                    await websocket.send_json({'type': 'pts', 't': round(pts, 3)})
                    last_pts_sent = pts
            except queue.Empty:
                if not thread.is_alive():
                    if processor.error:
                        await websocket.send_json({
                            'type': 'error',
                            'message': processor.error
                        })
                    break
                continue

        recv_task.cancel()
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                'type': 'error',
                'message': str(e)
            })
        except:
            pass
    finally:
        if processor:
            processor.stop()  # libera cap/proc inmediatamente
        # Limpiar sesión de audio con retraso (el proxy-audio HTTP puede seguir activo)
        if audio_session_id:
            async def delayed_cleanup(sid):
                await asyncio.sleep(300)  # 5 minutos
                if sid in audio_sessions:
                    del audio_sessions[sid]
                    print(f"Audio session eliminada (delayed): {sid}")
            asyncio.ensure_future(delayed_cleanup(audio_session_id))
        try:
            await websocket.send_json({'type': 'complete'})
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando TeslaTube V1.0...")
    print("📺 Abre http://localhost:8001 en tu navegador")
    uvicorn.run(app, host="0.0.0.0", port=8002)
