# Department 7: Trading Engine (Freqtrade)
FROM freqtradeorg/freqtrade:stable

USER root

# Install additional dependencies
RUN pip install --no-cache-dir \
    aiomqtt>=2.0.0 \
    redis>=5.0.0 \
    elasticsearch>=8.12.0

# Copy custom libraries
COPY lib/ /freqtrade/lib/

# Copy trading configuration
COPY department_7/config/ /freqtrade/config/
COPY department_7/strategies/ /freqtrade/user_data/strategies/

# Create necessary directories
RUN mkdir -p /freqtrade/user_data/data /freqtrade/user_data/logs /freqtrade/user_data/backtest_results

# Fix permissions
RUN chown -R ftuser:ftuser /freqtrade

USER ftuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/api/v1/ping || exit 1

# Run freqtrade
CMD ["freqtrade", "trade", "--config", "/freqtrade/config/config.json"]
