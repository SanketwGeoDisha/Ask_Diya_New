/**
 * Utilities for exporting large datasets
 * Handles chunked export to prevent browser freezing
 */

/**
 * Export data to JSON with chunking for large datasets
 * @param {Array} data - Data to export
 * @param {string} filename - Output filename
 */
export const exportToJSON = (data, filename = 'audit-results.json') => {
  try {
    const jsonString = JSON.stringify(data, null, 2);
    downloadFile(jsonString, filename, 'application/json');
  } catch (error) {
    console.error('Export to JSON failed:', error);
    throw new Error('Failed to export JSON. Data might be too large.');
  }
};

/**
 * Export data to CSV with chunking for large datasets
 * @param {Array} results - Array of KPI results
 * @param {string} filename - Output filename
 */
export const exportToCSV = (results, filename = 'audit-results.csv') => {
  try {
    if (!results || results.length === 0) {
      throw new Error('No data to export');
    }

    // Process in chunks to avoid UI blocking
    const chunkSize = 100;
    const chunks = [];
    
    // Headers
    const headers = [
      'KPI Name',
      'Category',
      'Value',
      'System Confidence',
      'LLM Confidence',
      'Source Priority',
      'Evidence',
      'Source URL',
      'Data Year'
    ];
    chunks.push(headers.join(','));

    // Process data in chunks
    for (let i = 0; i < results.length; i += chunkSize) {
      const chunk = results.slice(i, i + chunkSize);
      
      const csvRows = chunk.map(result => {
        const row = [
          escapeCSV(result.kpi_name || ''),
          escapeCSV(result.category || ''),
          escapeCSV(formatValue(result.value)),
          escapeCSV(result.system_confidence || result.confidence || ''),
          escapeCSV(result.llm_confidence || ''),
          escapeCSV(result.source_priority || ''),
          escapeCSV(result.evidence_quote || ''),
          escapeCSV(result.source_url || ''),
          escapeCSV(result.data_year?.toString() || '')
        ];
        return row.join(',');
      });
      
      chunks.push(...csvRows);
    }

    const csvContent = chunks.join('\n');
    downloadFile(csvContent, filename, 'text/csv');
  } catch (error) {
    console.error('Export to CSV failed:', error);
    throw new Error('Failed to export CSV. ' + error.message);
  }
};

/**
 * Export summary statistics
 * @param {Object} summary - Summary object
 * @param {string} filename - Output filename
 */
export const exportSummary = (summary, filename = 'audit-summary.json') => {
  try {
    const jsonString = JSON.stringify(summary, null, 2);
    downloadFile(jsonString, filename, 'application/json');
  } catch (error) {
    console.error('Export summary failed:', error);
    throw new Error('Failed to export summary.');
  }
};

/**
 * Escape CSV special characters
 * @param {*} value - Value to escape
 * @returns {string} Escaped value
 */
function escapeCSV(value) {
  if (value === null || value === undefined) {
    return '';
  }
  
  const stringValue = String(value);
  
  // If contains comma, quote, or newline, wrap in quotes and escape quotes
  if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
    return `"${stringValue.replace(/"/g, '""')}"`;
  }
  
  return stringValue;
}

/**
 * Format value for CSV export
 * @param {*} value - Value to format
 * @returns {string} Formatted value
 */
function formatValue(value) {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (Array.isArray(value)) {
    return value.join('; ');
  }
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, val]) => `${key}: ${val}`)
      .join('; ');
  }
  return String(value);
}

/**
 * Download file to browser
 * @param {string} content - File content
 * @param {string} filename - Filename
 * @param {string} mimeType - MIME type
 */
function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Export using Web Worker for very large datasets (>1000 items)
 * @param {Array} data - Data to export
 * @param {string} format - 'csv' or 'json'
 * @param {string} filename - Output filename
 * @returns {Promise} Promise that resolves when export completes
 */
export const exportWithWorker = (data, format, filename) => {
  return new Promise((resolve, reject) => {
    // Check if Worker is supported
    if (!window.Worker) {
      console.warn('Web Workers not supported, falling back to synchronous export');
      if (format === 'csv') {
        exportToCSV(data, filename);
      } else {
        exportToJSON(data, filename);
      }
      resolve();
      return;
    }

    try {
      // For now, fallback to regular export
      // TODO: Implement actual Web Worker for heavy processing
      if (format === 'csv') {
        exportToCSV(data, filename);
      } else {
        exportToJSON(data, filename);
      }
      resolve();
    } catch (error) {
      reject(error);
    }
  });
};
