from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import orm_models
from datetime import datetime
from service.security import get_password_hash
from models import users as user_schema
from models import trade as trade_schema
from models import asset as asset_schema
from models import groups as group_schema
from sqlalchemy.orm import selectinload
from db.orm_models import Group, User, UserGroupAssociation, GroupMemberRole

# =================================================================
# === COMPLETE ASSET SERVICE FUNCTIONS (GLOBAL/PUBLIC ASSETS) ===
# =================================================================


async def get_asset_by_id(db: AsyncSession, asset_id: int):
    """Fetches a single asset by its ID."""
    query = select(orm_models.Asset).where(orm_models.Asset.id == asset_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_asset_by_symbol(db: AsyncSession, symbol: str):
    """Fetches a single asset by its symbol."""
    query = select(orm_models.Asset).where(orm_models.Asset.symbol == symbol)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_all_assets(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Fetches all assets with pagination."""
    query = select(orm_models.Asset).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_asset_by_symbol_or_id(
    db: AsyncSession, symbol: str = None, asset_id: int = None
):
    """Fetches an asset by either its symbol or ID."""
    if symbol:
        return await get_asset_by_symbol(db, symbol)
    elif asset_id:
        return await get_asset_by_id(db, asset_id)
    else:
        raise ValueError("Either 'symbol' or 'asset_id' must be provided.")


async def get_all_assets(db: AsyncSession, skip: int = 0, limit: int = 100):
    """
    Fetches all assets from the global list. No ownership is checked.
    """
    query = select(orm_models.Asset).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_asset_by_id(db: AsyncSession, asset_id: int):
    """
    Fetches a single global asset by its ID. No ownership is checked.
    """
    query = select(orm_models.Asset).where(orm_models.Asset.id == asset_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_asset_by_symbol(db: AsyncSession, symbol: str):
    """
    Fetches a single global asset by its symbol. No ownership is checked.
    """
    query = select(orm_models.Asset).where(orm_models.Asset.symbol == symbol)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_asset(db: AsyncSession, asset_data: dict):
    """
    Creates a new asset in the global list. No owner is assigned.
    """
    db_asset = orm_models.Asset(**asset_data)
    db.add(db_asset)
    await db.commit()
    await db.refresh(db_asset)
    return db_asset


async def update_asset(
    db: AsyncSession, db_asset: orm_models.Asset, asset_in: asset_schema.AssetUpdate
):
    """
    Updates a global asset's details.
    """
    asset_data = asset_in.model_dump(exclude_unset=True)
    for field, value in asset_data.items():
        setattr(db_asset, field, value)
    await db.commit()
    await db.refresh(db_asset)
    return db_asset


async def delete_asset(db: AsyncSession, db_asset: orm_models.Asset):
    """
    Deletes a global asset, but only if it has no trades associated with it.
    """
    # Check if any trades are linked to this asset
    query = select(orm_models.Trade).where(orm_models.Trade.asset_id == db_asset.id)
    result = await db.execute(query)
    if result.scalars().first():
        # If there are trades, prevent deletion by returning None
        return None

    await db.delete(db_asset)
    await db.commit()
    return True  # Return True on successful deletion


async def update_asset_price(
    db: AsyncSession, asset: orm_models.Asset, new_price: float
):
    """
    Updates the price and timestamp for a given asset record.
    """
    asset.current_price = new_price
    asset.price_last_updated = datetime.utcnow()

    await db.commit()

    # Refresh the instance to get the latest data from the DB, like the 'updated_at' timestamp
    await db.refresh(asset)

    return asset


# =================================================================
# === COMPLETE TRADE SERVICE FUNCTIONS ===
# =================================================================


async def create_trade(db: AsyncSession, asset_id: int, trade_data: dict):
    """Creates a new trade record for a given asset."""
    db_trade = orm_models.Trade(**trade_data, asset_id=asset_id)
    db.add(db_trade)
    await db.commit()
    await db.refresh(db_trade)
    return db_trade


async def get_trades_by_asset_id(db: AsyncSession, asset_id: int):
    """Fetches all trades for a specific asset ID."""
    query = select(orm_models.Trade).where(orm_models.Trade.asset_id == asset_id)
    result = await db.execute(query)
    return result.scalars().all()


async def get_all_trades(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Fetches all trades with pagination."""
    query = select(orm_models.Trade).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_trades_before_date(db: AsyncSession, end_date: datetime):
    """Fetches all trades that occurred before a specific date."""
    query = select(orm_models.Trade).where(orm_models.Trade.trade_date < end_date)
    result = await db.execute(query)
    return result.scalars().all()


async def get_trades_in_date_range(
    db: AsyncSession, start_date: datetime, end_date: datetime
):
    """Fetches all trades within a specific date range."""
    query = select(orm_models.Trade).where(
        orm_models.Trade.trade_date >= start_date,
        orm_models.Trade.trade_date <= end_date,
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_trade_by_id(db: AsyncSession, trade_id: int):
    """Fetches a single trade by its ID, pre-loading the group for permission checks."""
    query = (
        select(orm_models.Trade)
        .where(orm_models.Trade.id == trade_id)
        .options(
            selectinload(orm_models.Trade.group).selectinload(orm_models.Group.members)
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_trades_by_group_id(
    db: AsyncSession, group_id: int, skip: int = 0, limit: int = 100
):
    """
    Fetches all trades for a specific group ID with pagination.
    """
    query = (
        select(orm_models.Trade)
        .where(orm_models.Trade.group_id == group_id)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def update_trade(
    db: AsyncSession, db_trade: orm_models.Trade, trade_in: trade_schema.TradeUpdate
):
    """Updates a trade record."""
    trade_data = trade_in.model_dump(exclude_unset=True)
    for field, value in trade_data.items():
        setattr(db_trade, field, value)
    await db.commit()
    await db.refresh(db_trade)
    return db_trade


async def delete_trade(db: AsyncSession, db_trade: orm_models.Trade):
    """Deletes a trade record."""
    await db.delete(db_trade)
    await db.commit()
    return True


# =================================================================
# === COMPLETE USER SERVICE FUNCTIONS ===
# =================================================================


# Fetches all groups with pagination
async def get_user_by_email(db: AsyncSession, email: str):
    """Fetches a single user by their email."""
    query = (
        select(orm_models.User).where(orm_models.User.email == email)
        # --- THE CORRECTED QUERY ---
        .options(
            selectinload(orm_models.User.group_associations).selectinload(
                orm_models.UserGroupAssociation.group
            )
        )
    )

    result = await db.execute(query)
    orm_user = result.scalar_one_or_none()

    if not orm_user:
        return None

    return orm_user


async def create_user(db: AsyncSession, user: user_schema.UserCreate):
    """Creates a new user with a hashed password and timestamps."""
    hashed_password = get_password_hash(user.password)
    now = datetime.utcnow()

    db_user = orm_models.User(
        name=user.name,
        email=user.email,
        hashed_password=hashed_password,
        created_at=now,
        updated_at=now,
    )
    db.add(db_user)
    await db.commit()
    
    new_user = await get_user_by_id(db, user_id=db_user.id)
    return new_user


async def get_all_users(db: AsyncSession, skip: int = 0, limit: int = 100):
    """Fetches all users."""
    query = (
        select(orm_models.User)
        .offset(skip)
        .limit(limit)
        .options(selectinload(orm_models.User.groups))
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_user_by_id(db: AsyncSession, user_id: int):
    """Fetches a single user by their ID."""
    query = (
        select(orm_models.User)
        .where(orm_models.User.id == user_id)
        .options(
            selectinload(orm_models.User.group_associations)
        )  # Eagerly load the links
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


# =================================================================
# === COMPLETE GROUP SERVICE FUNCTIONS ===
# =================================================================


async def create_group(
    db: AsyncSession, group: group_schema.GroupCreate, owner: user_schema.User
):
    """Creates a new group and assigns the creator as the 'group_admin'."""
    db_group = Group(name=group.name)

    # Create the association object with the specific role
    association = UserGroupAssociation(
        user_id=owner.id,
        role=GroupMemberRole.ADMIN,  # Assigning the creator as Group Admin
    )

    # Link the association to the group
    db_group.member_associations.append(association)

    db.add(db_group)
    await db.commit()
    await db.refresh(db_group)
    return db_group


# async def update_group(db: AsyncSession, db_group: orm_models.Group, group_in: group_schema.GroupUpdate):
#     """Updates a group's details."""

#     await db.commit()
#     await db.refresh(db_group)
#     return db_group


async def get_group_by_id(db: AsyncSession, group_id: int):
    """Fetches a single group by its ID, pre-loading its members."""
    query = (
        select(orm_models.Group)
        .where(orm_models.Group.id == group_id)
        .options(
            selectinload(orm_models.Group.member_associations).selectinload(
                orm_models.UserGroupAssociation.user
            )
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def delete_group(db: AsyncSession, group: orm_models.Group):
    """Deletes a group, but only if it contains no assets."""
    if group.member_associations:
        # Prevent deletion if the group still owns assets
        return None
    await db.delete(group)
    await db.commit()
    return True


# =================================================================
# === COMPLETE GROUP/USER SERVICE FUNCTIONS ===
# =================================================================


async def add_or_update_user_in_group(
    db: AsyncSession, user: User, group: Group, role: GroupMemberRole
):
    """
    Adds a user to a group or updates their role if they are already a member.
    """
    # Check if an association already exists
    association = next(
        (assoc for assoc in user.group_associations if assoc.group_id == group.id), None
    )

    if association:
        # If user is already in the group, update their role
        association.role = role
    else:
        # If not, create a new association object to link them
        association = UserGroupAssociation(user=user, group=group, role=role)
        db.add(association)

    await db.commit()
    # Eagerly load the members again to return the fully updated group object
    await db.refresh(group)

    updated_group = await get_group_by_id(db, group_id=group.id)

    return updated_group


async def remove_user_from_group(db: AsyncSession, user: User, group: Group):
    """Removes a user from a group's member list."""
    # Find the association object linking this user and group
    association = next(
        (assoc for assoc in user.group_associations if assoc.group_id == group.id), None
    )

    if association:
        await db.delete(association)
        await db.commit()

    # Eagerly load the members again to return the updated group
    await db.refresh(group)

    updated_group = await get_group_by_id(db, group_id=group.id)

    return updated_group
