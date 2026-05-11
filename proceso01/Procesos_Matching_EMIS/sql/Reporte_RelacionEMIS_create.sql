/* ======================================================================
   Tabla [ETL].[dbo].[Reporte_RelacionEMIS]
   Aloja el resultado del pipeline EMIS — Matches_Detalle.

   Fuente: Procesos_Matching_EMIS\EMIS_Con_Historia_Fiscal.xlsx
           hoja "Matches_Detalle".

   Mapeo columna Excel  ↔  columna SQL:
     D-U-N-S® Number    →  DUNS_Number      (PK)
     Company Name       →  Company_Name
     Facturado          →  Facturado
     Revisado_CRM       →  Revisado_CRM
     Detalle_Matches    →  Detalle_Matches  (JSON consolidado)
     Ultima_Facturacion →  Ultima_Facturacion
     Score_Max          →  Score_Max
     Fuente_Match       →  Fuente_Match

   Script idempotente: si la tabla ya existe, no la modifica. Para
   recrearla forzadamente, descomenta el DROP al inicio.
   ====================================================================== */

USE [ETL];
GO

-- Para forzar recreación, descomenta esta línea (DESTRUCTIVO):
-- IF OBJECT_ID('dbo.Reporte_RelacionEMIS', 'U') IS NOT NULL DROP TABLE [dbo].[Reporte_RelacionEMIS];

IF NOT EXISTS (
    SELECT 1
    FROM sys.tables
    WHERE name = 'Reporte_RelacionEMIS' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    -- Tipo VARCHAR para campos ASCII puro (DUNS, fechas string, Fuente_Match, fecha de carga)
    -- → ahorra ~50% bytes y mejora densidad de páginas / índices.
    -- NVARCHAR se mantiene en Company_Name y Detalle_Matches porque contienen
    -- acentos del español y caracteres Unicode del JSON con ensure_ascii=False.
    CREATE TABLE [dbo].[Reporte_RelacionEMIS] (
        [DUNS_Number]        VARCHAR(20)     NOT NULL,    -- Número D-U-N-S®, ASCII puro
        [Company_Name]       NVARCHAR(500)   NULL,        -- Nombres con acentos / Unicode
        [Facturado]          BIT             NOT NULL  CONSTRAINT DF_RelEMIS_Facturado    DEFAULT (0),
        [Revisado_CRM]       BIT             NOT NULL  CONSTRAINT DF_RelEMIS_RevisadoCRM  DEFAULT (0),
        [Detalle_Matches]    NVARCHAR(MAX)   NULL,        -- JSON: {IdsCRM, IdsCliente, RFCs_Asociados, Regimenes_Fiscales, Variantes_Nombre, Razones_LLM}
        [Ultima_Facturacion] VARCHAR(20)     NULL,        -- "YYYY/MM/DD" o vacío
        [Score_Max]          FLOAT           NULL,
        [Fuente_Match]       VARCHAR(50)     NULL,        -- auto | llm | crm_sin_factura_auto | crm_sin_factura_llm | crm_sin_factura_mixto | sin_match
        [Fecha_Carga]        DATETIME        NOT NULL  CONSTRAINT DF_RelEMIS_FechaCarga   DEFAULT (GETDATE()),
        CONSTRAINT PK_Reporte_RelacionEMIS PRIMARY KEY CLUSTERED ([DUNS_Number])
    );

    CREATE NONCLUSTERED INDEX IX_RelEMIS_Facturado_Revisado
        ON [dbo].[Reporte_RelacionEMIS] ([Facturado], [Revisado_CRM]);

    CREATE NONCLUSTERED INDEX IX_RelEMIS_FuenteMatch
        ON [dbo].[Reporte_RelacionEMIS] ([Fuente_Match]);

    PRINT '✓ Tabla [dbo].[Reporte_RelacionEMIS] creada con PK + 2 índices.';
END
ELSE
BEGIN
    PRINT '✓ Tabla [dbo].[Reporte_RelacionEMIS] ya existía — sin cambios.';
END
GO


/* ======================================================================
   Validaciones rápidas (queries de smoke-test)
   ====================================================================== */

-- Estructura
EXEC sp_help 'dbo.Reporte_RelacionEMIS';

-- Primeras 5 filas (vacío justo después de crear)
SELECT TOP 5 * FROM [dbo].[Reporte_RelacionEMIS];

-- Distribución por Fuente_Match (después del primer load)
-- SELECT [Fuente_Match], COUNT(*) AS Total
-- FROM [dbo].[Reporte_RelacionEMIS]
-- GROUP BY [Fuente_Match]
-- ORDER BY Total DESC;

-- Pendientes de revisión CRM (Diario debería verlos a 0 en estado estable)
-- SELECT COUNT(*) AS Pendientes
-- FROM [dbo].[Reporte_RelacionEMIS]
-- WHERE [Facturado] = 0 AND [Revisado_CRM] = 0;
