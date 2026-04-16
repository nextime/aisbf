"""
Payment System Background Scheduler

Runs periodic jobs for blockchain monitoring, subscription renewals,
payment retries, wallet consolidation, and price updates.
Uses distributed locking for horizontal scaling.
"""
import asyncio
import logging
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)


class PaymentScheduler:
    """
    Background scheduler for payment system periodic tasks.
    
    Runs jobs at configured intervals with distributed locking
    to support horizontal scaling across multiple instances.
    """
    
    def __init__(self, db_manager, payment_service):
        """
        Initialize payment scheduler.
        
        Args:
            db_manager: DatabaseManager instance
            payment_service: PaymentService instance
        """
        self.db = db_manager
        self.payment_service = payment_service
        self.running = False
        self.tasks = []
        
        # Job configurations (name, interval_seconds, handler)
        self.jobs = [
            ('blockchain_monitor', 60, self._run_blockchain_monitor),
            ('subscription_renewal', 300, self._run_subscription_renewal),
            ('payment_retry', 300, self._run_payment_retry),
            ('wallet_consolidation', 3600, self._run_wallet_consolidation),
            ('price_update', 300, self._run_price_update),
            ('notification_queue', 60, self._run_notification_queue),
        ]
    
    async def start(self):
        """
        Start the scheduler.
        
        Launches background tasks for each job.
        """
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        self.running = True
        logger.info("Starting payment scheduler...")
        
        # Start each job in its own task
        for job_name, interval, handler in self.jobs:
            task = asyncio.create_task(
                self._run_job_loop(job_name, interval, handler)
            )
            self.tasks.append(task)
        
        logger.info(f"Started {len(self.jobs)} scheduler jobs")
    
    async def stop(self):
        """
        Stop the scheduler.
        
        Cancels all running tasks and waits for them to complete.
        """
        if not self.running:
            return
        
        logger.info("Stopping payment scheduler...")
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)
        
        self.tasks.clear()
        logger.info("Payment scheduler stopped")
    
    async def _run_job_loop(
        self,
        job_name: str,
        interval: int,
        handler: Callable
    ):
        """
        Run a job in a loop at specified interval.
        
        Args:
            job_name: Name of the job
            interval: Interval in seconds
            handler: Async function to execute
        """
        logger.info(f"Started job loop: {job_name} (interval: {interval}s)")
        
        while self.running:
            try:
                # Try to acquire distributed lock
                if await self._acquire_lock(job_name):
                    try:
                        logger.debug(f"Running job: {job_name}")
                        await handler()
                    finally:
                        await self._release_lock(job_name)
                else:
                    logger.debug(f"Job {job_name} already running on another instance")
                
            except asyncio.CancelledError:
                logger.info(f"Job loop cancelled: {job_name}")
                break
            except Exception as e:
                logger.error(f"Error in job {job_name}: {e}", exc_info=True)
            
            # Wait for next interval
            await asyncio.sleep(interval)
    
    async def _acquire_lock(self, job_name: str, timeout: int = 300) -> bool:
        """
        Acquire distributed lock for job.
        
        Uses database row locking to ensure only one instance runs the job.
        
        Args:
            job_name: Name of the job
            timeout: Lock timeout in seconds
            
        Returns:
            True if lock acquired, False otherwise
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                
                # Check if lock exists and is not expired
                if self.db.db_type == 'sqlite':
                    expires_check = f"datetime('now', '-{timeout} seconds')"
                else:
                    expires_check = f"DATE_SUB(NOW(), INTERVAL {timeout} SECOND)"
                
                cursor.execute(f"""
                    SELECT locked_at, locked_by
                    FROM distributed_locks
                    WHERE lock_name = {placeholder}
                """, (job_name,))
                
                row = cursor.fetchone()
                
                # If lock exists and not expired, can't acquire
                if row:
                    locked_at = row[0]
                    # Check if expired
                    if self.db.db_type == 'sqlite':
                        cursor.execute(f"""
                            SELECT datetime('now') > datetime(?, '+{timeout} seconds')
                        """, (locked_at,))
                    else:
                        cursor.execute(f"""
                            SELECT NOW() > DATE_ADD(?, INTERVAL {timeout} SECOND)
                        """, (locked_at,))
                    
                    is_expired = cursor.fetchone()[0]
                    
                    if not is_expired:
                        return False
                
                # Acquire or refresh lock
                instance_id = f"scheduler_{id(self)}"
                
                if row:
                    # Update existing lock
                    cursor.execute(f"""
                        UPDATE distributed_locks
                        SET locked_at = CURRENT_TIMESTAMP,
                            locked_by = {placeholder}
                        WHERE lock_name = {placeholder}
                    """, (instance_id, job_name))
                else:
                    # Insert new lock
                    cursor.execute(f"""
                        INSERT INTO distributed_locks (lock_name, locked_at, locked_by)
                        VALUES ({placeholder}, CURRENT_TIMESTAMP, {placeholder})
                    """, (job_name, instance_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error acquiring lock for {job_name}: {e}")
            return False
    
    async def _release_lock(self, job_name: str):
        """
        Release distributed lock for job.
        
        Args:
            job_name: Name of the job
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                
                cursor.execute(f"""
                    DELETE FROM distributed_locks
                    WHERE lock_name = {placeholder}
                """, (job_name,))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error releasing lock for {job_name}: {e}")
    
    # Job handlers
    
    async def _run_blockchain_monitor(self):
        """Run blockchain monitoring job"""
        logger.info("Running blockchain monitor job")
        try:
            await self.payment_service.blockchain_monitor.check_crypto_payments()
        except Exception as e:
            logger.error(f"Blockchain monitor job failed: {e}", exc_info=True)
    
    async def _run_subscription_renewal(self):
        """Run subscription renewal job"""
        logger.info("Running subscription renewal job")
        try:
            await self.payment_service.renewal_processor.process_renewals()
        except Exception as e:
            logger.error(f"Subscription renewal job failed: {e}", exc_info=True)
    
    async def _run_payment_retry(self):
        """Run payment retry job"""
        logger.info("Running payment retry job")
        try:
            from aisbf.payments.subscription.retry import PaymentRetryProcessor
            retry_processor = PaymentRetryProcessor(
                self.db,
                self.payment_service.subscription_manager
            )
            await retry_processor.process_retries()
        except Exception as e:
            logger.error(f"Payment retry job failed: {e}", exc_info=True)
    
    async def _run_wallet_consolidation(self):
        """Run wallet consolidation job"""
        logger.info("Running wallet consolidation job")
        try:
            from aisbf.payments.crypto.consolidation import WalletConsolidator
            consolidator = WalletConsolidator(
                self.db,
                self.payment_service.wallet_manager
            )
            await consolidator.consolidate_wallets()
            await consolidator.process_consolidation_queue()
        except Exception as e:
            logger.error(f"Wallet consolidation job failed: {e}", exc_info=True)
    
    async def _run_price_update(self):
        """Run price update job"""
        logger.info("Running price update job")
        try:
            await self.payment_service.price_service.update_all_prices()
        except Exception as e:
            logger.error(f"Price update job failed: {e}", exc_info=True)
    
    async def _run_notification_queue(self):
        """Run notification queue processing job"""
        logger.info("Running notification queue job")
        try:
            from aisbf.payments.notifications.email import EmailNotificationService
            email_service = EmailNotificationService(self.db)
            await email_service.process_notification_queue()
        except Exception as e:
            logger.error(f"Notification queue job failed: {e}", exc_info=True)
    
    def get_job_status(self) -> Dict:
        """
        Get status of all scheduled jobs.
        
        Returns:
            Dict with job statuses
        """
        status = {
            'running': self.running,
            'jobs': []
        }
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            for job_name, interval, _ in self.jobs:
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                
                cursor.execute(f"""
                    SELECT locked_at, locked_by
                    FROM distributed_locks
                    WHERE lock_name = {placeholder}
                """, (job_name,))
                
                row = cursor.fetchone()
                
                job_status = {
                    'name': job_name,
                    'interval': interval,
                    'locked': bool(row),
                    'locked_at': row[0] if row else None,
                    'locked_by': row[1] if row else None
                }
                
                status['jobs'].append(job_status)
        
        return status
    
    async def run_job_now(self, job_name: str):
        """
        Manually trigger a job to run immediately.
        
        Args:
            job_name: Name of the job to run
        """
        # Find job handler
        handler = None
        for name, _, h in self.jobs:
            if name == job_name:
                handler = h
                break
        
        if not handler:
            raise ValueError(f"Unknown job: {job_name}")
        
        logger.info(f"Manually running job: {job_name}")
        
        # Try to acquire lock
        if await self._acquire_lock(job_name):
            try:
                await handler()
                logger.info(f"Job {job_name} completed successfully")
            finally:
                await self._release_lock(job_name)
        else:
            raise RuntimeError(f"Job {job_name} is already running")
