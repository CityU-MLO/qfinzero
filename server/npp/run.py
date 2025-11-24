#!/usr/bin/env python3
# run.py
import sys
import os
import logging

# 添加 src 到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Starting news data pipeline...")
    
    try:
        # Parse command line arguments
        import argparse
        parser = argparse.ArgumentParser(description='Run news data pipeline')
        parser.add_argument('--use-simple', action='store_true', default=True, 
                          help='Use simplified pipeline version')
        parser.add_argument('--no-simple', dest='use_simple', action='store_false', 
                          help='Use full pipeline version')
        parser.add_argument('--days', type=int, default=1, 
                          help='Number of historical days to process')
        args = parser.parse_args()
        
        # Import pipelines
        from pipelines.news_pipeline import NewsDataPipeline, SimpleNewsDataPipeline
        from config.settings import OUTPUTS_DIR
        
        # Select pipeline version based on arguments
        use_simple = args.use_simple
        
        if use_simple:
            logger.info("Using simplified pipeline version...")
            pipeline = SimpleNewsDataPipeline()
        else:
            logger.info("Using full pipeline version...")
            pipeline = NewsDataPipeline()
        
        # Run pipeline
        result = pipeline.run_pipeline(days_back=args.days)
        
        logger.info(f"Pipeline completed: {result}")
        logger.info(f"Output directory: {OUTPUTS_DIR}")
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.info("💡 Tip: Ensure all required modules exist and are correctly written")
        return 1
    except Exception as e:
        logger.error(f"Runtime error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())