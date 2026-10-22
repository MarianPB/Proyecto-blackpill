function r = metricas_banda(x, fs, banda, n_arm, ponderarA)
% METRICAS_BANDA  THD, THD+N, SINAD, SNR, ENOB y SFDR de un tono, integrando solo dentro de 'banda'.
%   r = metricas_banda(x, fs)                 banda 20 Hz - 20 kHz, armónicos hasta el 7.o
%   r = metricas_banda(x, fs, [400 20e3], 7)
%   r = metricas_banda(x, fs, [20 20e3], 7, true)   con ponderación A (IEC 61672, 0 dB en 1 kHz)
%
% Cómo se calcula:
%   1. Espectro de potencia de toda la captura con ventana Blackman-Harris (su lóbulo principal
%      ocupa +-4 bins, por eso cada tono se suma en +-ANCHO bins).
%   2. P1 = potencia del fundamental (el pico más alto dentro de la banda).
%   3. Ph = suma de los armónicos 2..n_arm que caen dentro de la banda.
%   4. Pn = todo lo demás dentro de la banda (sin DC, fundamental ni armónicos) = ruido + espurios.
%   THD = Ph/P1,  THD+N = (Ph+Pn)/P1,  SNR = P1/Pn,  SINAD = -THD+N,  ENOB = (SINAD-1,76)/6,02
%   SFDR = fundamental contra el componente más alto que no sea él (armónico o espurio), en la banda.

if nargin < 3, banda = [20 20e3]; end
if nargin < 4, n_arm = 7; end
if nargin < 5, ponderarA = false; end
ANCHO = 5;                                     % bins a cada lado de un tono

x = x(:) - mean(x);
n = numel(x);
w = blackmanharris(n);
X = fft(x .* w);
p = abs(X(1:floor(n / 2) + 1)).^2;             % potencia por bin (escala relativa: solo importan cocientes)
f = (0:numel(p) - 1)' * fs / n;
df = fs / n;
p0 = p;                                        % sin ponderar: para el nivel del tono
if ponderarA
    p = p .* ponderacion_A(f);
end

en_banda = f >= banda(1) & f <= banda(2);

% fundamental: pico más alto dentro de la banda
idx = find(en_banda);
[~, k] = max(p(idx));
k1 = idx(k);
f0 = f(k1);

usado = false(size(p));
usado(1:ANCHO + 1) = true;                     % DC y lo que se le pega

[P1, b] = tono(p, k1, ANCHO);
usado(b) = true;

Ph = 0;
arm = [];
for h = 2:n_arm
    fh = h * f0;
    if fh > banda(2) || fh > fs / 2
        break
    end
    kh = round(fh / df) + 1;
    % el armónico real puede caer un bin al costado: busco el máximo cerca
    cerca = max(1, kh - 2):min(numel(p), kh + 2);
    [~, j] = max(p(cerca));
    [ph, b] = tono(p, cerca(j), ANCHO);
    Ph = Ph + ph;
    usado(b) = true;
    arm(end + 1, :) = [fh, 10 * log10(ph / P1)]; %#ok<AGROW>
end

ruido = en_banda & ~usado;
Pn = sum(p(ruido));

% SFDR: el pico más alto de lo que no es el fundamental (los armónicos sí cuentan)
otros = en_banda;
otros(max(1, k1 - ANCHO):min(numel(p), k1 + ANCHO)) = false;
otros(1:ANCHO + 1) = false;
[~, ke] = max(p .* otros);
p_esp = tono(p, ke, ANCHO);                   % sumado igual que el fundamental

r.f0 = f0;
r.nivel_dBFS = 10 * log10(4 * tono(p0, k1, ANCHO) / (n * sum(w.^2)));   % amplitud de pico del tono (1 = fondo de escala)
r.thd = 10 * log10(Ph / P1);
r.thdn = 10 * log10((Ph + Pn) / P1);
r.sinad = -r.thdn;
r.snr = 10 * log10(P1 / Pn);
r.enob = (r.sinad - 1.76) / 6.02;
r.sfdr = 10 * log10(P1 / p_esp);
r.f_espurio = f(ke);
r.armonicos = arm;                              % [frecuencia, dBc] de cada armónico
r.banda = banda;
r.ponderarA = ponderarA;
end


function [pot, bins] = tono(p, k, ancho)
% potencia de un tono: suma de los bins de su lóbulo principal
bins = max(1, k - ancho):min(numel(p), k + ancho);
pot = sum(p(bins));
end


function wA = ponderacion_A(f)
% ponderación A en POTENCIA, normalizada a 1 en 1 kHz
ra = @(f) (12194^2 * f.^4) ./ ((f.^2 + 20.6^2) .* sqrt((f.^2 + 107.7^2) .* (f.^2 + 737.9^2)) .* (f.^2 + 12194^2));
wA = (ra(f) / ra(1000)).^2;
end
