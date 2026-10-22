%% PISO DE RUIDO  Carga una captura de grabar_piso.py y calcula el ruido de cada canal.
clear; close all;

[f, p] = uigetfile(fullfile(fileparts(mfilename('fullpath')), '..', 'capturas', 'piso_*.mat'), 'Elegí la captura');
load(fullfile(p, f));          % trae L, R (una columna por paquete de 1 s), fs, perdidas

banda = [20 20e3];             % banda de audio [Hz]
P_FS = 0.5;                    % potencia de un seno de fondo de escala = 0 dBFS

fprintf('\n%s   (%d paquetes, tramas perdidas: %d)\n\n', f, size(L, 2), perdidas);
fprintf('paquete    L [dBFS]    R [dBFS]    (ruido en %g Hz - %g Hz)\n', banda(1), banda(2));

ruido = zeros(size(L, 2), 2);
for k = 1:size(L, 2)
    for c = 1:2
        if c == 1, x = L(:, k); else, x = R(:, k); end
        x = x - mean(x);                                        % sin DC
        ruido(k, c) = 10 * log10(bandpower(x, fs, banda) / P_FS);
    end
    fprintf('%5d     %7.1f     %7.1f\n', k, ruido(k, 1), ruido(k, 2));
end

% promedio de potencias (no de dB)
prom = 10 * log10(mean(10 .^ (ruido / 10)));
fprintf('\nPISO DE RUIDO:  L = %.1f dBFS    R = %.1f dBFS\n', prom(1), prom(2));

%% Valores para comparar con la hoja de datos (toda la captura junta)
% El rango dinámico del PCM3060 se da en 20 Hz - 20 kHz con ponderación A: DR = -(piso ponderado A).
ra = @(f) (12194^2 * f.^4) ./ ((f.^2 + 20.6^2) .* sqrt((f.^2 + 107.7^2) .* (f.^2 + 737.9^2)) .* (f.^2 + 12194^2));

fprintf('\n%-34s %10s %10s\n', '', 'L', 'R');
v = zeros(5, 2);
for c = 1:2
    if c == 1, x = L(:); else, x = R(:); end
    [pxx, fr] = pwelch(x - mean(x), blackmanharris(65536), 32768, 65536, fs);     % densidad [1/Hz]
    A = (ra(fr) / ra(1000)).^2;                                                   % ponderación A en potencia
    red = false(size(fr));
    for h = 1:400
        red = red | abs(fr - 50 * h) < 4;                                         % 50 Hz y sus armónicos
    end
    en = @(a, b) fr >= a & fr <= b;
    integ = @(w, m) 10 * log10(trapz(fr(m), pxx(m) .* w(m)) / P_FS);
    uno = ones(size(fr));
    v(1, c) = integ(uno, en(20, 20e3));
    v(2, c) = integ(uno, en(400, 20e3));
    v(3, c) = integ(A, en(20, 20e3));
    v(4, c) = integ(uno, en(20, 20e3) & ~red);
    v(5, c) = integ(A, en(20, 20e3) & ~red);
end
nombres = {'20 Hz-20 kHz [dBFS]', '400 Hz-20 kHz [dBFS]', '20 Hz-20 kHz ponderado A [dBFS]', ...
           '20 Hz-20 kHz sin la red [dBFS]', 'ponderado A sin la red [dBFS]'};
for i = 1:5
    fprintf('%-34s %10.1f %10.1f\n', nombres{i}, v(i, 1), v(i, 2));
end
fprintf('\nRANGO DINÁMICO (A):  L = %.1f dB   R = %.1f dB   (hoja de datos: típ. 99, mín. 95)\n', -v(3, 1), -v(3, 2));
fprintf('             sin la red:  L = %.1f dB   R = %.1f dB\n', -v(5, 1), -v(5, 2));

%% Espectro promediado de todos los paquetes
figure;
for c = 1:2
    if c == 1, x = L(:); nombre = 'L'; else, x = R(:); nombre = 'R'; end
    [pxx, fr] = pwelch(x - mean(x), hann(32768), 16384, 32768, fs, 'power');
    semilogx(fr, 10 * log10(pxx / P_FS), 'DisplayName', nombre); hold on;
end
grid on; xlim([10 fs / 2]); legend;
xlabel('f [Hz]'); ylabel('dBFS');
title('Piso de ruido', 'Interpreter', 'none');
