%% ANALIZAR_SESION  Analiza todas las capturas de una sesión de medir_todo.py y arma el resumen.
% Run y elegir la carpeta capturas\sesion_AAAAMMDD_HHMM. Deja en esa carpeta:
%   resultados.csv   una fila por captura (se abre con Excel)
%   resumen.txt      lo mismo que se imprime acá, medida por medida, contra la hoja de datos
% Necesita Signal Processing Toolbox. Tarda un par de minutos (son ~35 capturas).

clear; close all;

carpeta = uigetdir(fullfile(fileparts(mfilename('fullpath')), '..', 'capturas'), 'Elegí la carpeta de la sesión');
if isequal(carpeta, 0), error('No se eligió ninguna carpeta'); end
archivos = dir(fullfile(carpeta, '*.mat'));
[~, orden] = sort({archivos.name});
archivos = archivos(orden);

%% 1. Una fila por captura
F = {};                                % filas de la tabla (cell de structs)
for i = 1:numel(archivos)
    c = leer_captura(fullfile(carpeta, archivos(i).name));
    fprintf('%2d/%d  %s\n', i, numel(archivos), c.nombre);
    if isempty(c.canal)
        % sin señal (M3): una fila por canal
        for ch = 'lr'
            q = ruido_banda(c.(ch), c.fs);
            F{end + 1} = fila_base(c, ch, q, []); %#ok<SAGROW>
        end
    else
        x = c.(c.canal);
        if c.canal == 'l', otro = c.r; else, otro = c.l; end
        r = struct('b400', metricas_banda(x, c.fs, [400 20e3], 7, false), ...
                   'b20',  metricas_banda(x, c.fs, [20 20e3], 7, false), ...
                   'bA',   metricas_banda(x, c.fs, [20 20e3], 7, true));
        r.extra = extras_tono(x, otro, c.fs, r.b400.f0);
        F{end + 1} = fila_base(c, c.canal, [], r); %#ok<SAGROW>
    end
end
T = struct2table([F{:}]);
writetable(T, fullfile(carpeta, 'resultados.csv'));

%% 2. Resumen medida por medida
L = @(varargin) sprintf(varargin{:});
res = {};
res{end + 1} = L('RESUMEN DE LA SESIÓN  %s', carpeta);
res{end + 1} = L('Perdidas de tramas en total: %d (tiene que ser 0)', sum(T.perdidas));
res{end + 1} = '';

% M3: piso de ruido de la cadena
M = T(T.medida == "M3", :);
if ~isempty(M)
    res{end + 1} = 'M3  PISO DE RUIDO DE LA CADENA (DAC encendido en silencio), promedio de las capturas';
    for ch = ["L", "R"]
        m = M(M.canal == ch, :);
        res{end + 1} = L('  %s: 20-20k %.1f | 400-20k %.1f | A %.1f | sin red %.1f | A sin red %.1f dBFS', ch, ...
            pdb(m.ruido_20k), pdb(m.ruido_400), pdb(m.ruido_A), pdb(m.ruido_sinred), pdb(m.ruido_A_sinred));
        res{end + 1} = L('     RANGO DINÁMICO (A): %.1f dB  (sin la red: %.1f dB)   hoja de datos ADC: típ. 99, mín. 95', ...
            -pdb(m.ruido_A), -pdb(m.ruido_A_sinred));
    end
    res{end + 1} = '';
end

% M4: nivel de trabajo
M = T(T.medida == "M4" | T.medida == "M4final", :);
if ~isempty(M)
    res{end + 1} = 'M4  NIVEL DE TRABAJO (1 kHz por tabla)';
    for k = 1:height(M)
        res{end + 1} = L('  %-12s %s  amplitud %g %%  nivel %.2f dBFS', M.nombre(k), M.canal(k), M.amplitud(k), M.nivel(k));
    end
    res{end + 1} = '  Esperado: ~-1,5 dBFS al 63 % (sin Rs), L y R a menos de 0,5 dB; el control final igual al inicial.';
    res{end + 1} = '';
end

% M5: linealidad
M = sortrows(T(T.medida == "M5", :), 'amplitud', 'descend');
if height(M) > 1
    res{end + 1} = 'M5  LINEALIDAD DEL ATENUADOR (canal L)';
    pedido = -0.5 * round(-20 * log10(M.amplitud / 100) / 0.5);    % lo que escribe el firmware (pasos de 0,5 dB)
    for k = 1:height(M)
        if k == 1
            res{end + 1} = L('  %3g %%  pedido %6.1f dB  nivel %7.2f dBFS', M.amplitud(k), pedido(k), M.nivel(k));
        else
            esc = M.nivel(k) - M.nivel(k - 1); esp = pedido(k) - pedido(k - 1);
            res{end + 1} = L('  %3g %%  pedido %6.1f dB  nivel %7.2f dBFS   escalón %6.2f dB (esperado %5.1f, error %+.2f)', ...
                M.amplitud(k), pedido(k), M.nivel(k), esc, esp, esc - esp);
        end
    end
    res{end + 1} = '  Esperado: error de cada escalón menor que 0,1 dB.';
    res{end + 1} = '';
end

% M7 / M8: pureza y separación
for med = ["M7", "M8"]
    M = T(T.medida == med, :);
    if isempty(M), continue; end
    res{end + 1} = L('%s  PUREZA canal %s, 1 kHz por tabla (%d capturas: promedio [mín. a máx.])', med, M.canal(1), height(M));
    res{end + 1} = L('  nivel             %s dBFS', rango(M.nivel));
    res{end + 1} = L('  THD               %s dB', rango(M.thd_400));
    res{end + 1} = L('  THD+N 400-20k     %s dB     (20-20k: %s, A: %s)', rango(M.thdn_400), rango(M.thdn_20k), rango(M.thdn_A));
    res{end + 1} = L('  SNR   400-20k     %s dB     (20-20k: %s, A: %s)', rango(M.snr_400), rango(M.snr_20k), rango(M.snr_A));
    res{end + 1} = L('  SINAD 400-20k     %s dB   ENOB %s bits', rango(M.sinad_400), rango(M.enob_400));
    res{end + 1} = L('  SFDR  400-20k     %s dB   (peor componente en %s Hz)', rango(M.sfdr_400), strjoin(string(round(M.f_peor)), ', '));
    res{end + 1} = L('  separación        %s dB', rango(M.separacion));
    res{end + 1} = '  Propuesta (mínimo): THD+N < -60 dB, SNR > 80 dB, SFDR > 70 dB, separación > 80 dB.';
    res{end + 1} = '  Hoja de datos ADC: THD+N -93 dB típ. (-85 máx.), separación 96 dB típ.';
    res{end + 1} = '';
end

% M9: seno por acumulador contra tabla
M = T(T.medida == "M9", :);
if ~isempty(M)
    s = M(contains(M.nombre, "seno"), :); t = M(contains(M.nombre, "tabla"), :);
    res{end + 1} = 'M9  SENO POR ACUMULADOR CONTRA TABLA (1 kHz, canal L)';
    res{end + 1} = L('                       seno (acumulador)         tabla');
    res{end + 1} = L('  THD+N 400-20k        %-24s %s dB', rango(s.thdn_400), rango(t.thdn_400));
    res{end + 1} = L('  SNR 400-20k          %-24s %s dB', rango(s.snr_400), rango(t.snr_400));
    res{end + 1} = L('  SFDR 400-20k         %-24s %s dB', rango(s.sfdr_400), rango(t.sfdr_400));
    res{end + 1} = L('  peor NO armónico     %-24s %s dBc', rango(s.esp_no_arm), rango(t.esp_no_arm));
    res{end + 1} = L('    en                 %-24s %s Hz', strjoin(string(round(s.f_esp_no_arm)), ', '), strjoin(string(round(t.f_esp_no_arm)), ', '));
    res{end + 1} = '  Esperado: con el seno por acumulador, un espurio de ~-78 dBc cerca de 10,1 kHz; con la tabla no.';
    res{end + 1} = '';
end

% M10: 995,4 Hz paso contra tabla, espurio cerca de 47,8 kHz
M = T(T.medida == "M10", :);
if ~isempty(M)
    res{end + 1} = 'M10 995,4 Hz POR PASO CONTRA POR TABLA (mayor componente entre 46 y 48,8 kHz)';
    for k = 1:height(M)
        res{end + 1} = L('  %-10s %7.1f dBc en %.0f Hz', M.nombre(k), M.esp_478(k), M.f_esp_478(k));
    end
    res{end + 1} = '  Esperado: en "paso" un pico en ~47,8 kHz que en "tabla" no está (cualitativo: el filtro del codec atenúa ahí).';
    res{end + 1} = '';
end

% M15: multitono, intermodulación alrededor de 7 kHz
M = T(T.medida == "M15", :);
if ~isempty(M)
    res{end + 1} = 'M15 MULTITONO 60 Hz + 7 kHz: bandas laterales respecto del tono de 7 kHz';
    res{end + 1} = L('  7000 +- 60 Hz: %.1f dBc     7000 +- 120 Hz: %.1f dBc', M.imd_60(1), M.imd_120(1));
    res{end + 1} = '  Cuanto más abajo, menos intermodulación (mezcla entre los dos tonos).';
    res{end + 1} = '';
end

% M11: rango dinámico EIAJ
M = T(T.medida == "M11", :);
if ~isempty(M)
    res{end + 1} = 'M11 RANGO DINÁMICO (EIAJ: señal a -60 dB, 20 Hz-20 kHz, ponderado A)';
    for k = 1:height(M)
        if M.nivel(k) < -45 && M.nivel(k) > -75
            res{end + 1} = L('  %s: nivel %.1f dBFS  ->  RANGO DINÁMICO %.1f dB (A)   (sin ponderar %.1f dB)', ...
                M.canal(k), M.nivel(k), M.sinad_A(k) - M.nivel(k), M.sinad_20k(k) - M.nivel(k));
        else
            res{end + 1} = L('  %s: nivel %.1f dBFS: NO quedó en -60 dB, esta captura no sirve para el rango dinámico', M.canal(k), M.nivel(k));
        end
    end
    res{end + 1} = '  Hoja de datos ADC: típ. 99 dB, mín. 95 dB (a fs = 48 kHz).';
    res{end + 1} = '';
end

fid = fopen(fullfile(carpeta, 'resumen.txt'), 'w', 'n', 'UTF-8');
for k = 1:numel(res)
    fprintf('%s\n', res{k});
    fprintf(fid, '%s\n', res{k});
end
fclose(fid);
fprintf('\nGuardado: resultados.csv y resumen.txt en %s\n', carpeta);


%% ---------------------------------------------------------------- funciones
function f = fila_base(c, ch, q, r)
% una fila de la tabla; los campos que no aplican quedan en NaN
f.archivo = string(c.archivo);
f.nombre = string(c.nombre);
f.medida = string(c.medida);
f.canal = string(upper(ch));
f.amplitud = c.amplitud;
f.perdidas = c.perdidas;
campos = {'nivel', 'thd_400', 'thdn_400', 'sinad_400', 'snr_400', 'enob_400', 'sfdr_400', 'f_peor', ...
          'thdn_20k', 'snr_20k', 'sinad_20k', 'thdn_A', 'snr_A', 'sinad_A', 'separacion', ...
          'esp_no_arm', 'f_esp_no_arm', 'esp_478', 'f_esp_478', 'imd_60', 'imd_120', ...
          'ruido_20k', 'ruido_400', 'ruido_A', 'ruido_sinred', 'ruido_A_sinred'};
for k = 1:numel(campos), f.(campos{k}) = NaN; end
if ~isempty(q)
    f.ruido_20k = q.t20; f.ruido_400 = q.t400; f.ruido_A = q.A;
    f.ruido_sinred = q.sinred; f.ruido_A_sinred = q.A_sinred;
end
if ~isempty(r)
    f.nivel = r.b400.nivel_dBFS;
    f.thd_400 = r.b400.thd; f.thdn_400 = r.b400.thdn; f.sinad_400 = r.b400.sinad;
    f.snr_400 = r.b400.snr; f.enob_400 = r.b400.enob; f.sfdr_400 = r.b400.sfdr; f.f_peor = r.b400.f_espurio;
    f.thdn_20k = r.b20.thdn; f.snr_20k = r.b20.snr; f.sinad_20k = r.b20.sinad;
    f.thdn_A = r.bA.thdn; f.snr_A = r.bA.snr; f.sinad_A = r.bA.sinad;
    e = r.extra;
    f.separacion = e.separacion;
    f.esp_no_arm = e.esp_no_arm; f.f_esp_no_arm = e.f_esp_no_arm;
    f.esp_478 = e.esp_478; f.f_esp_478 = e.f_esp_478;
    f.imd_60 = e.imd_60; f.imd_120 = e.imd_120;
end
end


function q = ruido_banda(x, fs)
% ruido sin señal en dBFS (0 dBFS = seno de fondo de escala): igual que piso_de_ruido.m
x = x - mean(x);
[pxx, fr] = pwelch(x, blackmanharris(65536), 32768, 65536, fs);
ra = @(f) (12194^2 * f.^4) ./ ((f.^2 + 20.6^2) .* sqrt((f.^2 + 107.7^2) .* (f.^2 + 737.9^2)) .* (f.^2 + 12194^2));
A = (ra(fr) / ra(1000)).^2;
red = false(size(fr));
for h = 1:400, red = red | abs(fr - 50 * h) < 4; end
en = @(a, b) fr >= a & fr <= b;
I = @(wt, m) 10 * log10(trapz(fr(m), pxx(m) .* wt(m)) / 0.5);
uno = ones(size(fr));
q.t20 = I(uno, en(20, 20e3));
q.t400 = I(uno, en(400, 20e3));
q.A = I(A, en(20, 20e3));
q.sinred = I(uno, en(20, 20e3) & ~red);
q.A_sinred = I(A, en(20, 20e3) & ~red);
end


function e = extras_tono(x, otro, fs, f0)
% separación, peor espurio NO armónico (truncación), pico cerca de 47,8 kHz e intermodulación en 7 kHz
n = numel(x);
w = blackmanharris(n);
nivel = @(P, k) 10 * log10(4 * sum(P(max(1, k - 5):min(numel(P), k + 5))) / (n * sum(w.^2)));
Px = abs(fft((x - mean(x)) .* w)).^2;  Px = Px(1:floor(n / 2) + 1);
Po = abs(fft((otro - mean(otro)) .* w)).^2;  Po = Po(1:floor(n / 2) + 1);
f = (0:numel(Px) - 1)' * fs / n;
bin = @(fx) round(fx / (fs / n)) + 1;

k0 = bin(f0);
n0 = nivel(Px, k0);

% separación: el tono en el otro canal; si no se ve sobre el ruido, "mayor que"
no = nivel(Po, k0);
ruido_local = 10 * log10(4 * 11 * mean(Po([k0 - 60:k0 - 20, k0 + 20:k0 + 60])) / (n * sum(w.^2)));
e.separacion = n0 - max(no, ruido_local);

% peor componente que no sea el fundamental ni un armónico, en 400 Hz - 20 kHz
% (se dejan afuera +-20 Hz alrededor de cada armónico, donde está la base del tono, y +-3 Hz de la red hasta 1 kHz)
libre = f >= 400 & f <= 20e3;
for h = 1:ceil(20e3 / f0) + 1
    libre(abs(f - h * f0) < 20) = false;
end
for h = 1:20                                   % la red (hasta 1 kHz; arriba ya no pesa)
    libre(abs(f - 50 * h) < 3) = false;
end
[~, k] = max(Px .* libre);
e.esp_no_arm = nivel(Px, k) - n0;
e.f_esp_no_arm = f(k);

% mayor componente entre 46 y 48,8 kHz (M10)
zona = f >= 46e3 & f <= 48.8e3;
[~, k] = max(Px .* zona);
e.esp_478 = nivel(Px, k) - n0;
e.f_esp_478 = f(k);

% intermodulación alrededor de 7 kHz (M15): respecto del tono de 7 kHz
k7 = bin(7000);
[~, j] = max(Px(k7 - 3:k7 + 3)); k7 = k7 - 4 + j;
n7 = nivel(Px, k7);
lat = @(df) max(nivel(Px, bin(7000 - df)), nivel(Px, bin(7000 + df))) - n7;
e.imd_60 = lat(60);
e.imd_120 = lat(120);
end


function v = pdb(x)
% promedio de valores en dB, promediando potencias
v = 10 * log10(mean(10 .^ (x / 10)));
end


function s = rango(x)
x = x(~isnan(x));
if isempty(x), s = '-'; return; end
if numel(x) == 1, s = sprintf('%.1f', x); return; end
s = sprintf('%.1f [%.1f a %.1f]', mean(x), min(x), max(x));
end
