%% ANALIZAR_CAPTURA  Captura con un tono (grabar.py): forma de onda, espectro y métricas de pureza.
% Correr por secciones (Ctrl+Enter). Necesita Signal Processing Toolbox.

clear; close all;

c = leer_captura();            % sin argumento abre el cuadro para elegir el .mat
canal = 'l';                   % canal que tiene la señal: 'l' o 'r'

x = c.(canal);
if canal == 'l', otro = c.r; else, otro = c.l; end
fs = c.fs;

fprintf('\n%s  (%s)  canal %s\n', c.nombre, c.fecha, upper(canal));
fprintf('comandos: %s\n', strjoin(c.comandos, '  '));
fprintf('%.2f s, %d muestras, tramas perdidas: %d\n', numel(x) / fs, numel(x), c.perdidas);
fprintf('pico de la señal: %.2f dBFS de fondo de escala (si pasa de -0,5, puede estar recortando)\n', ...
    20 * log10(max(abs(x))));

%% Forma de onda (los primeros 5 ms)
n = round(5e-3 * fs);
figure('Name', 'Tiempo');
plot(c.t(1:n) * 1e3, x(1:n));
grid on; xlabel('t [ms]'); ylabel('amplitud [FS]');
title(sprintf('%s - canal %s', c.nombre, upper(canal)), 'Interpreter', 'none');

%% Espectro (Welch, Blackman-Harris de 65536 puntos: 1,5 Hz por bin; 0 dBFS = seno de fondo de escala)
nfft = 65536;
figure('Name', 'Espectro');
[pxx, f] = pwelch(x - mean(x), blackmanharris(nfft), nfft / 2, nfft, fs, 'power');
semilogx(f, 10 * log10(pxx / 0.5), 'DisplayName', ['canal ' upper(canal)]); hold on;
[pxx, f] = pwelch(otro - mean(otro), blackmanharris(nfft), nfft / 2, nfft, fs, 'power');
semilogx(f, 10 * log10(pxx / 0.5), 'DisplayName', 'el otro canal');
grid on; xlim([10 fs / 2]); legend;
xlabel('f [Hz]'); ylabel('dBFS');
title(sprintf('%s', c.nombre), 'Interpreter', 'none');

%% Métricas (ver metricas_banda.m): dos bandas, y 20 Hz - 20 kHz con ponderación A
casos = { [400 20e3], false, '400 Hz-20 kHz'; ...
          [20 20e3],  false, '20 Hz-20 kHz'; ...
          [20 20e3],  true,  '20 Hz-20 kHz (A)' };
R = cell(1, 3);
for i = 1:3
    R{i} = metricas_banda(x, fs, casos{i, 1}, 7, casos{i, 2});
end

fprintf('\ntono: %.2f Hz, nivel %.2f dBFS\n\n', R{1}.f0, R{1}.nivel_dBFS);
fprintf('%-10s', ''); fprintf('%18s', casos{:, 3}); fprintf('\n');
filas = {'THD', 'thd', 'dB'; 'THD+N', 'thdn', 'dB'; 'SINAD', 'sinad', 'dB'; ...
         'SNR', 'snr', 'dB'; 'ENOB', 'enob', 'bits'; 'SFDR', 'sfdr', 'dB'};
for j = 1:size(filas, 1)
    fprintf('%-10s', filas{j, 1});
    for i = 1:3
        fprintf('%18s', sprintf('%.1f %s', R{i}.(filas{j, 2}), filas{j, 3}));
    end
    fprintf('\n');
end
fprintf('peor componente (400 Hz-20 kHz): %.1f Hz\n', R{1}.f_espurio);
for i = 1:size(R{1}.armonicos, 1)
    fprintf('  armónico %d (%.0f Hz): %6.1f dBc\n', i + 1, R{1}.armonicos(i, 1), R{1}.armonicos(i, 2));
end

%% Separación entre canales: cuánto del tono aparece en el otro canal (el otro tiene que estar en OFF)
m = numel(otro);
w = blackmanharris(m);
P = abs(fft((otro - mean(otro)) .* w)).^2;
k = round(R{1}.f0 / (fs / m)) + 1;
a_dbfs = @(pot) 10 * log10(4 * pot / (m * sum(w.^2)));
nivel_otro = a_dbfs(sum(P(k - 5:k + 5)));
vecinos = [k - 60:k - 20, k + 20:k + 60];
ruido_local = a_dbfs(11 * mean(P(vecinos)));        % lo que darían esos 11 bins si solo hubiera ruido
if nivel_otro > ruido_local + 10
    fprintf('\ntono en el otro canal: %.1f dBFS  ->  SEPARACIÓN %.1f dB\n', ...
        nivel_otro, R{1}.nivel_dBFS - nivel_otro);
else
    fprintf('\nel tono no aparece en el otro canal (queda bajo su ruido, %.1f dBFS)  ->  SEPARACIÓN mayor que %.1f dB\n', ...
        ruido_local, R{1}.nivel_dBFS - ruido_local);
end

%% Rango dinámico (EIAJ): solo vale con la señal cerca de -60 dBFS (M11)
if R{3}.nivel_dBFS < -45 && R{3}.nivel_dBFS > -75
    fprintf('\nRANGO DINÁMICO (EIAJ, A): %.1f dB   (sin ponderar: %.1f dB)\n', ...
        R{3}.sinad - R{3}.nivel_dBFS, R{2}.sinad - R{2}.nivel_dBFS);
end
