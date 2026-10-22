function c = leer_captura(archivo)
% LEER_CAPTURA  Carga un .mat grabado con grabar.py.
%   c = leer_captura('capturas/20261020_101500_M7_L_1k_50.mat')
%   c = leer_captura()           abre un cuadro para elegir el archivo
%
% Devuelve una estructura con:
%   c.l, c.r     cada canal normalizado a fondo de escala (+-1 = 0 dBFS), columna double
%   c.t          tiempo de cada muestra [s]
%   c.fs         frecuencia de muestreo [Hz]
%   c.perdidas   tramas perdidas (si no es 0 la señal tiene huecos en c.pos_perdidas)
%   c.nombre, c.fecha, c.comandos, c.nota, c.archivo

if nargin < 1
    carpeta = fullfile(fileparts(mfilename('fullpath')), '..', 'capturas');
    [f, p] = uigetfile(fullfile(carpeta, '*.mat'), 'Elegí una captura');
    if isequal(f, 0)
        error('No se eligió ningún archivo');
    end
    archivo = fullfile(p, f);
end

d = load(archivo);

c.archivo = archivo;
c.fs = double(d.fs);
c.l = double(d.L(:)) / double(d.full_scale);
c.r = double(d.R(:)) / double(d.full_scale);
c.t = (0:numel(c.l) - 1)' / c.fs;
c.perdidas = double(d.perdidas);
c.pos_perdidas = double(d.pos_perdidas(:));
c.nombre = strtrim(char(d.nombre));
c.fecha = strtrim(char(d.fecha));
c.nota = strtrim(char(d.nota));
if isempty(d.comandos)
    c.comandos = {};
else
    c.comandos = cellfun(@(s) strtrim(char(s)), d.comandos(:)', 'UniformOutput', false);
end

% campos que agrega medir_todo.py (en las capturas sueltas de grabar.py no están)
c.canal = '';
c.medida = '';
c.amplitud = NaN;
if isfield(d, 'canal'),    c.canal = strtrim(char(d.canal)); end
if isfield(d, 'medida'),   c.medida = strtrim(char(d.medida)); end
if isfield(d, 'amplitud'), c.amplitud = double(d.amplitud); end

if c.perdidas > 0
    warning('%s: %d tramas perdidas, la señal tiene huecos', c.nombre, c.perdidas);
end
end
